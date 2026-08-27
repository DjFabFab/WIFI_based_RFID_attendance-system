from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.conf import settings
from .models import Student, Log
from .uid_utils import preprocess_uid
import datetime
import json
import os
import pathlib
import time
import requests


def get_alarm_display(payload: dict) -> dict:
    """Pure helper: parse Divera pull/all payload for display.

    Reuses :func:`divera_kiosk.parse_latest_alarm` semantics:

    * envelope ``{"success": true, "data": {"alarm": {"items": list|dict}}}``
    * ``closed`` falsy = active, ``newest`` = max int ``id`` (prefer newest
      active when any active exists)
    * missing / malformed never raises (returns ``active=False`` idle dict)

    Enriches the selected alarm for template rendering: extracts
    ``title`` / ``address`` / ``lat`` / ``lng`` / ``priority`` / ``duration``
    / ``date`` / ``closed`` / ``id`` / ``vehicle_ids`` / ``group_ids`` and
    resolves ``vehicle_names`` via ``data.get("vehicle")`` or
    ``data.get("vehicles")`` and ``group_names`` via ``data.get("cluster")`` /
    ``data.get("group")`` / ``data.get("ucr")`` (handles dict keys as
    ``str``/``int`` and nested ``{name}`` dicts). Always returns a dict with
    keys ``active``, ``error``, ``title``, ``address``, ``lat``, ``lng``,
    ``priority``, ``duration``, ``date``, ``closed``, ``id``, ``vehicle_ids``,
    ``group_ids``, ``vehicle_names``, ``group_names``.
    """
    idle = {
        "active": False,
        "error": None,
        "title": "",
        "address": "",
        "lat": None,
        "lng": None,
        "priority": False,
        "duration": "",
        "date": "",
        "closed": None,
        "id": None,
        "vehicle_ids": [],
        "group_ids": [],
        "vehicle_names": [],
        "group_names": [],
        "status_counts": {},
        "status_display": [],
        "role_counts": {"AGT": 0, "MA": 0, "GF": 0},
        "crew_list": [],
        "role_names": {"AGT": [], "MA": [], "GF": []},
    }
    try:
        if not isinstance(payload, dict):
            return dict(idle)
        if not payload.get("success"):
            return dict(idle)
        data = payload.get("data")
        if not isinstance(data, dict):
            return dict(idle)
        alarm = data.get("alarm")
        if not isinstance(alarm, dict):
            return dict(idle)
        items = alarm.get("items")
        if isinstance(items, dict):
            items = list(items.values())
        if not isinstance(items, list):
            return dict(idle)
        alarms = [a for a in items if isinstance(a, dict)]
        if not alarms:
            return dict(idle)
        active = any(not a.get("closed") for a in alarms)
        active_alarms = [a for a in alarms if not a.get("closed")]
        candidates = active_alarms if active_alarms else alarms

        def _id_val(a):
            v = a.get("id")
            return v if isinstance(v, int) else -1

        selected = max(candidates, key=_id_val)

        title = selected.get("title")
        if title is None:
            title = selected.get("name") or selected.get("text") or ""
        if not isinstance(title, str):
            title = str(title) if title is not None else ""
        address = selected.get("address")
        if address is None:
            address = selected.get("location") or selected.get("ort") or ""
        if not isinstance(address, str):
            if isinstance(address, dict):
                address = address.get("address") or address.get("street") or ""
                if not isinstance(address, str):
                    address = str(address) if address else ""
            else:
                address = str(address) if address not in (None, "") else ""
        lat = None
        for k in ("lat", "latitude", "latitud"):
            if k in selected and selected[k] not in (None, ""):
                lat = selected[k]
                break
        lng = None
        for k in ("lng", "longitude", "lon", "long"):
            if k in selected and selected[k] not in (None, ""):
                lng = selected[k]
                break

        def _clean_coord(v):
            if v is None or v == "":
                return None
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                try:
                    return float(s.replace(",", "."))
                except ValueError:
                    return None
            return None

        lat = _clean_coord(lat)
        lng = _clean_coord(lng)
        prio_raw = selected.get("priority")
        if isinstance(prio_raw, bool):
            priority = prio_raw
        elif isinstance(prio_raw, int):
            priority = bool(prio_raw)
        elif isinstance(prio_raw, str):
            priority = prio_raw.strip().lower() not in ("", "false", "0", "no", "none")
            if not prio_raw.strip():
                priority = False
        else:
            priority = bool(prio_raw)
        duration = selected.get("duration")
        if duration is None:
            duration = selected.get("dauer") or ""
        if not isinstance(duration, str):
            duration = str(duration) if duration is not None else ""
        date_val = selected.get("date")
        if date_val is None:
            date_val = selected.get("ts")
            if date_val is None:
                date_val = selected.get("timestamp")
                if date_val is None:
                    date_val = selected.get("time") or ""
        if not isinstance(date_val, str):
            date_val = str(date_val) if date_val not in (None, "") else ""
        closed_raw = selected.get("closed")
        if "closed" in selected:
            closed = bool(closed_raw)
        else:
            closed = None
        alarm_id = selected.get("id")
        if not isinstance(alarm_id, int):
            try:
                alarm_id = int(alarm_id) if alarm_id not in (None, "") else None
            except (ValueError, TypeError):
                alarm_id = None
        vehicle_ids = None
        for k in ("vehicle", "vehicles", "vehicle_ids", "vehicles_ids"):
            if k in selected and selected[k] is not None:
                vehicle_ids = selected[k]
                break
        if vehicle_ids is None:
            vehicle_ids = []
        if isinstance(vehicle_ids, int):
            vehicle_ids = [vehicle_ids]
        elif isinstance(vehicle_ids, str):
            vehicle_ids = [vehicle_ids] if vehicle_ids.strip() else []
        elif isinstance(vehicle_ids, dict):
            vehicle_ids = list(vehicle_ids.values())
        if not isinstance(vehicle_ids, list):
            vehicle_ids = []
        norm_vehicle_ids = []
        for v in vehicle_ids:
            if isinstance(v, int):
                norm_vehicle_ids.append(v)
            elif isinstance(v, str):
                s = v.strip()
                if s.lstrip("-").isdigit():
                    try:
                        norm_vehicle_ids.append(int(s))
                    except ValueError:
                        pass
            elif isinstance(v, dict) and "id" in v:
                try:
                    norm_vehicle_ids.append(int(v["id"]))
                except (ValueError, TypeError):
                    pass
        vehicle_ids = norm_vehicle_ids
        group_ids = None
        for k in ("group", "groups", "cluster", "clusters", "ucr", "ucr_ids", "group_ids"):
            if k in selected and selected[k] is not None:
                group_ids = selected[k]
                break
        if group_ids is None:
            group_ids = []
        if isinstance(group_ids, int):
            group_ids = [group_ids]
        elif isinstance(group_ids, str):
            group_ids = [group_ids] if group_ids.strip() else []
        elif isinstance(group_ids, dict):
            group_ids = list(group_ids.values())
        if not isinstance(group_ids, list):
            group_ids = []
        norm_group_ids = []
        for g in group_ids:
            if isinstance(g, int):
                norm_group_ids.append(g)
            elif isinstance(g, str):
                s = g.strip()
                if s.lstrip("-").isdigit():
                    try:
                        norm_group_ids.append(int(s))
                    except ValueError:
                        pass
            elif isinstance(g, dict) and "id" in g:
                try:
                    norm_group_ids.append(int(g["id"]))
                except (ValueError, TypeError):
                    pass
        group_ids = norm_group_ids
        vehicle_map = {}
        for k in ("vehicle", "vehicles"):
            v = data.get(k)
            if isinstance(v, dict) and v:
                vehicle_map = v
                break
        if not vehicle_map:
            cluster_obj = data.get("cluster")
            if isinstance(cluster_obj, dict):
                v = cluster_obj.get("vehicle")
                if isinstance(v, dict) and v:
                    vehicle_map = v
        group_map = {}
        cluster_obj = data.get("cluster")
        if isinstance(cluster_obj, dict):
            g = cluster_obj.get("group")
            if isinstance(g, dict) and g:
                group_map = g
        if not group_map:
            for k in ("groups",):
                g = data.get(k)
                if isinstance(g, dict) and g:
                    group_map = g
                    break

        def _resolve(ids, mapping):
            if not ids:
                return []
            if not isinstance(mapping, dict) or not mapping:
                return [str(i) for i in ids]
            lookup = {}
            for mk, mv in mapping.items():
                lookup[str(mk)] = mv
                try:
                    ik = int(mk)
                    lookup[ik] = mv
                    lookup[str(ik)] = mv
                except (ValueError, TypeError):
                    pass
            names = []
            for iid in ids:
                mv = lookup.get(iid)
                if mv is None:
                    mv = lookup.get(str(iid))
                if mv is None:
                    names.append(str(iid))
                    continue
                if isinstance(mv, dict):
                    name = mv.get("name") or mv.get("title") or mv.get("label") or mv.get("value") or ""
                    if isinstance(name, str) and name.strip():
                        names.append(name.strip())
                    elif isinstance(name, str):
                        names.append(str(iid))
                    else:
                        names.append(str(name) if name not in (None, "") else str(iid))
                elif isinstance(mv, str):
                    names.append(mv)
                else:
                    names.append(str(mv) if mv not in (None, "") else str(iid))
            return names

        vehicle_names = _resolve(vehicle_ids, vehicle_map)
        group_names = _resolve(group_ids, group_map)

        status_counts = {}
        role_counts = {"AGT": 0, "MA": 0, "GF": 0}
        try:
            monitor = data.get("monitor")
            if isinstance(monitor, dict):
                m1 = monitor.get("1")
                if isinstance(m1, dict):
                    for sid, sdata in m1.items():
                        if isinstance(sdata, dict):
                            all_cnt = sdata.get("all", 0)
                            if all_cnt:
                                status_counts[str(sid)] = all_cnt
                    _available_colors = {"success", "primary", "info", "warning"}
                    _monitor_color_map = {"78645": "success", "78646": "warning", "78647": "danger", "78650": "primary", "79817": "secondary", "86776": "dark"}
                    default_role_map = {"AGT": [2], "MA": [62], "GF": [3, 4]}
                    role_map = dict(default_role_map)
                    try:
                        for p in [pathlib.Path(__file__).resolve().parent.parent / "deployment" / "alarm_roles.json",
                                  pathlib.Path(settings.BASE_DIR) / "deployment" / "alarm_roles.json"]:
                            if p.exists():
                                jm = json.loads(p.read_text(encoding="utf-8"))
                                if isinstance(jm, dict):
                                    for rk in ("AGT", "MA", "GF"):
                                        if rk in jm and isinstance(jm[rk], list):
                                            role_map[rk] = [int(x) for x in jm[rk] if str(x).lstrip("-").isdigit()]
                                break
                    except Exception:
                        pass
                    monitor_users = data.get("monitor", {}).get("3", {})
                    cluster_obj2 = data.get("cluster", {}).get("consumer", {})
                    for uid, udata in monitor_users.items():
                        if not isinstance(udata, dict):
                            continue
                        sid = str(udata.get("status", ""))
                        if _monitor_color_map.get(sid) not in _available_colors:
                            continue
                        uinfo = cluster_obj2.get(str(uid))
                        if not isinstance(uinfo, dict):
                            try:
                                uinfo = cluster_obj2.get(int(str(uid)))
                            except Exception:
                                uinfo = None
                        if not isinstance(uinfo, dict):
                            continue
                        quals = uinfo.get("qualifications") or []
                        if not isinstance(quals, list):
                            continue
                        qset = {int(q) for q in quals if str(q).lstrip("-").isdigit()}
                        for role, qids in role_map.items():
                            if any(q in qset for q in qids):
                                role_counts[role] += 1
        except Exception:
            pass

        crew_list = []
        role_names = {"AGT": [], "MA": [], "GF": []}
        try:
            _color_map_for_names = {}
            try:
                default_color_map2 = {"78645": "success", "78646": "warning", "78647": "danger", "78650": "primary", "79817": "secondary", "86776": "dark"}
                for p in [pathlib.Path(__file__).resolve().parent.parent / "deployment" / "alarm_status.json",
                          pathlib.Path(settings.BASE_DIR) / "deployment" / "alarm_status.json"]:
                    if p.exists():
                        jm = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(jm, dict):
                            default_color_map2.update({str(k): str(v) for k, v in jm.items()})
                        break
                _color_map_for_names = default_color_map2
            except Exception:
                _color_map_for_names = {"78645": "success", "78646": "warning", "78647": "danger", "78650": "primary", "79817": "secondary", "86776": "dark"}

            _role_map2 = {"AGT": [2], "MA": [62], "GF": [3, 4]}
            try:
                for p in [pathlib.Path(__file__).resolve().parent.parent / "deployment" / "alarm_roles.json",
                          pathlib.Path(settings.BASE_DIR) / "deployment" / "alarm_roles.json"]:
                    if p.exists():
                        jm = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(jm, dict):
                            for rk in ("AGT", "MA", "GF"):
                                if rk in jm and isinstance(jm[rk], list):
                                    _role_map2[rk] = [int(x) for x in jm[rk] if str(x).lstrip("-").isdigit()]
                        break
            except Exception:
                pass

            consumer_map = {}
            cluster_obj = data.get("cluster")
            if isinstance(cluster_obj, dict):
                consumer = cluster_obj.get("consumer")
                if isinstance(consumer, dict):
                    consumer_map = consumer

            _user_status = {}
            _user_status_ts = {}
            monitor = data.get("monitor")
            if isinstance(monitor, dict):
                monitor_users = monitor.get("3")
                if isinstance(monitor_users, dict):
                    for uid, udata in monitor_users.items():
                        if isinstance(udata, dict):
                            st = udata.get("status")
                            if st is not None:
                                _user_status[str(uid)] = str(st)
                            ts = udata.get("ts")
                            if ts:
                                _user_status_ts[str(uid)] = int(ts)

            def _relative_time(ts_val):
                now_ts = int(time.time())
                diff = now_ts - int(ts_val)
                if diff < 60:
                    return f"{diff}s"
                elif diff < 3600:
                    return f"{round(diff / 60)}min"
                elif diff < 86400:
                    return f"{round(diff / 3600)}h"
                else:
                    return f"{round(diff / 86400)}d"

            for uid, uinfo in consumer_map.items():
                if not isinstance(uinfo, dict):
                    continue
                uid_str = str(uid)
                name = uid_str
                fn = uinfo.get("firstname") or ""
                ln = uinfo.get("lastname") or ""
                std = uinfo.get("stdformat_name") or ""
                if isinstance(std, str) and std.strip():
                    name = std.strip()
                elif isinstance(fn, str) or isinstance(ln, str):
                    parts = [p for p in (fn, ln) if isinstance(p, str) and p.strip()]
                    name = " ".join(parts) if parts else uid_str
                user_sid = _user_status.get(uid_str, "")
                color = _color_map_for_names.get(user_sid, "secondary")
                ts = _user_status_ts.get(uid_str)
                crew_list.append({"name": name, "color": color, "since": _relative_time(ts) if ts else ""})

            if active and responded_user_ids:
                for uid in responded_user_ids:
                    uid_str = str(uid)
                    if any(c["name"] == uid_str or _resolve_name(consumer_map, uid_str) == c["name"] for c in crew_list):
                        continue
                    name = uid_str
                    uinfo = consumer_map.get(uid_str)
                    if not isinstance(uinfo, dict):
                        try:
                            uinfo = consumer_map.get(int(uid_str))
                        except (ValueError, TypeError):
                            pass
                    if isinstance(uinfo, dict):
                        fn = uinfo.get("firstname") or ""
                        ln = uinfo.get("lastname") or ""
                        std = uinfo.get("stdformat_name") or ""
                        if isinstance(std, str) and std.strip():
                            name = std.strip()
                        elif isinstance(fn, str) or isinstance(ln, str):
                            parts = [p for p in (fn, ln) if isinstance(p, str) and p.strip()]
                            name = " ".join(parts) if parts else uid_str
                    user_sid = _user_status.get(uid_str, "")
                    color = _color_map_for_names.get(user_sid, "secondary")
                    crew_list.append({"name": name, "color": color})

            def _resolve_name(cmap, uid):
                u = cmap.get(uid)
                if not isinstance(u, dict):
                    try:
                        u = cmap.get(int(uid))
                    except (ValueError, TypeError):
                        return uid
                if isinstance(u, dict):
                    std = u.get("stdformat_name") or ""
                    if isinstance(std, str) and std.strip():
                        return std.strip()
                    fn = u.get("firstname") or ""
                    ln = u.get("lastname") or ""
                    parts = [p for p in (fn, ln) if isinstance(p, str) and p.strip()]
                    return " ".join(parts) if parts else uid
                return uid

            if active:
                for uid in responded_user_ids:
                    uid_str = str(uid)
                    name = _resolve_name(consumer_map, uid_str)
                    user_sid = _user_status.get(uid_str, "")
                    color = _color_map_for_names.get(user_sid, "secondary")
                    if color in ("success", "primary", "info"):
                        uinfo = consumer_map.get(uid_str)
                        if not isinstance(uinfo, dict):
                            try:
                                uinfo = consumer_map.get(int(uid_str))
                            except (ValueError, TypeError):
                                pass
                        if isinstance(uinfo, dict):
                            quals = uinfo.get("qualifications") or uinfo.get("quals") or uinfo.get("roles") or []
                            if isinstance(quals, list):
                                qset = set()
                                for q in quals:
                                    try:
                                        qset.add(int(q))
                                    except Exception:
                                        continue
                                for role, qids in _role_map2.items():
                                    if any(q in qset for q in qids):
                                        if name not in role_names[role]:
                                            role_names[role].append(name)
            else:
                for uid, uinfo in consumer_map.items():
                    if not isinstance(uinfo, dict):
                        continue
                    name = _resolve_name(consumer_map, uid)
                    quals = uinfo.get("qualifications") or uinfo.get("quals") or uinfo.get("roles") or []
                    if isinstance(quals, list):
                        qset = set()
                        for q in quals:
                            try:
                                qset.add(int(q))
                            except Exception:
                                continue
                        for role, qids in _role_map2.items():
                            if any(q in qset for q in qids):
                                if name not in role_names[role]:
                                    role_names[role].append(name)

            _color_order = {"success": 0, "primary": 1, "info": 2, "warning": 3, "danger": 4, "dark": 5, "secondary": 6}
            crew_list.sort(key=lambda x: (_color_order.get(x["color"], 7), x["name"]))
        except Exception:
            crew_list = []
            role_names = {"AGT": [], "MA": [], "GF": []}

        # map status IDs to display labels/colors for kiosk (green/blue/yellow)
        # default: known Divera statuses -> colors, fallback to hash
        status_display = []
        color_map = {}
        try:
            # try to load status color mapping
            default_color_map = {"78645": "success", "78646": "warning", "78647": "danger", "78650": "primary", "79817": "secondary", "86776": "dark"}
            # attempt to load from file
            for p in [pathlib.Path(__file__).resolve().parent.parent / "deployment" / "alarm_status.json",
                      pathlib.Path(settings.BASE_DIR) / "deployment" / "alarm_status.json"]:
                if p.exists():
                    jm = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(jm, dict):
                        default_color_map.update({str(k): str(v) for k, v in jm.items()})
                    break
            color_map = default_color_map
        except Exception:
            color_map = {"78645": "success", "78646": "warning", "78647": "danger", "78650": "primary", "79817": "secondary", "86776": "dark"}
        for sid, cnt in status_counts.items():
            if str(sid) == "0":
                continue
            label = sid
            def _short_label(name):
                _map = {
                    "innerhalb 10 Minuten": "≤10min",
                    "über 10 Minuten": ">10min",
                    "Nicht einsatzbereit": "N.einsatzb.",
                    "Gerätehaus": "GH",
                    "Keine Alarmierung": "Kein Alarm",
                }
                return _map.get(name, name)
            try:
                status_name_map = {}
                cluster_status = {}
                cluster_obj = data.get("cluster")
                if isinstance(cluster_obj, dict):
                    cs = cluster_obj.get("status")
                    if isinstance(cs, dict):
                        cluster_status = cs
                for sk, sv in cluster_status.items():
                    if isinstance(sv, dict):
                        sname = sv.get("name") or ""
                        if sname:
                            status_name_map[str(sk)] = sname
                ucr_raw = data.get("ucr")
                if isinstance(ucr_raw, dict):
                    for ucr_uid, ucr_info in ucr_raw.items():
                        if isinstance(ucr_info, dict):
                            mapped_sid = ucr_info.get("status_id")
                            ucr_name = ucr_info.get("name") or ""
                            if mapped_sid is not None and ucr_name and str(mapped_sid) not in status_name_map:
                                status_name_map[str(mapped_sid)] = ucr_name
                resolved = status_name_map.get(str(sid))
                if resolved:
                    label = resolved
            except Exception:
                pass
            # color: green/blue/yellow requested -> map to bootstrap: success/primary/warning
            color = color_map.get(str(sid))
            if not color:
                # deterministic fallback: hash to one of three
                try:
                    h = int(sid) % 3
                    color = ["success", "primary", "warning"][h]
                except Exception:
                    color = "secondary"
            status_display.append({"id": sid, "label": str(label), "short": _short_label(str(label)), "count": cnt, "color": color})

        return {
            "active": active,
            "error": None,
            "title": title,
            "address": address,
            "lat": lat,
            "lng": lng,
            "priority": priority,
            "duration": duration,
            "date": date_val,
            "closed": closed if closed is not None else bool(selected.get("closed")),
            "id": alarm_id,
            "vehicle_ids": vehicle_ids,
            "group_ids": group_ids,
            "vehicle_names": vehicle_names,
            "group_names": group_names,
            "status_counts": status_counts,
            "status_display": status_display,
            "role_counts": role_counts,
            "crew_list": crew_list,
            "role_names": role_names,
        }
    except Exception:
        return dict(idle)


def index1(request):
	logf = Log.objects.filter(date=datetime.date.today()).order_by('-id')
	dataset = {'log': logf}
	return render(request, 'attendance/attendance.html', dataset)


def search(request):
	id_val = request.POST.get('search')
	if id_val:
		try:
			sel_user = Student.objects.get(card_id=int(id_val))
			logf = Log.objects.filter(
				ida=id_val,
				date__month=datetime.datetime.now().month,
				date__year=datetime.datetime.now().year
			).order_by('-id')
			return render(request, 'attendance/search.html', {'use': sel_user, 'log': logf})
		except (Student.DoesNotExist, ValueError):
			return redirect('/')
	return redirect('/')


def index(request):
	return render(request, 'attendance/index.html')


def process(request):
	uid = request.GET.get("uid", None)
	if uid is not None:
		try:
			card = preprocess_uid(uid)
		except ValueError:
			return HttpResponse("invalid uid", status=400)
	else:
		card = request.GET.get("card_id", "kuch nahi mila")
	# support deletion via ?card_id=...&delete=1
	delete_flag = request.GET.get('delete', None)
	# if delete flag present, try to delete today's open Log for the card
	if delete_flag is not None:
		try:
			cid = int(card)
		except (ValueError, TypeError):
			return HttpResponse('invalid card id')
		# find the most recent open Log for this card dated today
		open_log = Log.objects.filter(
			card_id=cid, time_out__isnull=True,
			date=datetime.date.today()).order_by('-time_in').first()
		if open_log:
			open_log.delete()
			return HttpResponse('deleted')
		else:
			return HttpResponse('no open entry')

	# normal process: create or update attendance
	try:
		card = int(card)
	except (TypeError, ValueError):
		return HttpResponse('invalid card id', status=400)
	user = Student.objects.filter(card_id=card).first()
	if user:
		ans = attend(user)
		return HttpResponse(ans)
	new_user = Student(card_id=card)
	new_user.save()
	return HttpResponse('registered successfully')


def attend(user):
	display_name = user.name if user.name and str(user.name).strip() else str(user.card_id)
	open_log = Log.objects.filter(
		card_id=user.card_id, time_out__isnull=True).order_by('id').first()
	if open_log:
		open_log.time_out = datetime.datetime.now()
		open_log.save()
		return 'logout'
	new_log = Log(ida=user.id, card_id=user.card_id, name=display_name, date=datetime.datetime.now(),
			  time_in=datetime.datetime.now(), status='')
	new_log.save()
	return 'auth'


def details1(request):
	users = Student.objects.order_by('-id')
	userset = {'users': users}
	return render(request, 'attendance/userdetails.html', userset)


def details(request):
	return render(request, 'attendance/details.html')


def manage1(request):
	users = Student.objects.order_by('-id')
	userset = {'users': users}
	return render(request, 'attendance/allusers.html', userset)


def manage(request):
	users = Student.objects.order_by('-id')
	selected_id = request.session.get('selected_card_id')
	selected_user = Student.objects.filter(id=selected_id).first() if selected_id else None
	return render(request, 'attendance/manage.html', {'users': users, 'selected_user': selected_user})


def card(request):
	if request.method != 'POST':
		return redirect('/manage')
	if request.POST.get("sel"):
		ids = request.POST.get('idsearch', 'kuch nahi mila')
		try:
			user = Student.objects.filter(id=int(ids)).first()
		except (ValueError, TypeError):
			user = None
		if user:
			messages.info(request, 'Card is Selected')
			request.session['selected_card_id'] = user.id
		else:
			messages.info(request, 'Card not found')
		return redirect('/manage')
	else:
		ids = request.POST.get('idsearch')
		try:
			cid = int(ids)
		except (ValueError, TypeError):
			messages.info(request, 'Card not found')
			return redirect('/manage')
		if Student.objects.filter(id=cid).exists():
			Student.objects.filter(id=cid).update(
				name=None, dob=None, sex=None, email=None, address=None)
			messages.info(request, 'Deleted Successfully')
		else:
			messages.info(request, 'Card not found')
		return redirect('/manage')


def edit(request):
	selected_id = request.POST.get('selected_card_id') or request.POST.get('idsearch') or request.session.get('selected_card_id')
	if selected_id is None or str(selected_id).strip() == '':
		messages.info(request, 'No Card was Selected')
		return redirect('/manage')
	try:
		selected_id = int(selected_id)
	except (ValueError, TypeError):
		messages.info(request, 'Card not found')
		return redirect('/manage')
	user = Student.objects.filter(id=selected_id).first()
	if user is None:
		messages.info(request, 'Card not found')
		return redirect('/manage')
	name = request.POST.get('name')
	dob = request.POST.get('date')
	email = request.POST.get('email')
	gender = request.POST.get('gender')
	address = request.POST.get('address')
	new = [name, dob, email, gender, address]
	old = [user.name, user.dob, user.email, user.sex, user.address]
	i = 0
	for item in new:
		if item == '' or item is None:
			new[i] = old[i]
		i = i + 1
	user.name = new[0]
	user.dob = new[1]
	user.email = new[2]
	user.sex = new[3]
	user.address = new[4]
	user.save()
	messages.info(request, 'Profile Updated')
	request.session.pop('selected_card_id', None)
	return redirect('/manage')


def present(request):
	logs = Log.objects.filter(
		date=datetime.date.today(), time_out__isnull=True).order_by('-id')
	data = [{'name': log.name, 'card_id': log.card_id,
			 'date': log.date.strftime('%d.%m.%Y')} for log in logs]
	return JsonResponse(data, safe=False)


def alarm(request):
    if request.method != "GET":
        return HttpResponse("Method Not Allowed", status=405)
    access_key = (os.environ.get("DIVERA_ACCESS_KEY") or getattr(settings, "DIVERA_ACCESS_KEY", "") or "").strip()
    api_url = os.environ.get("DIVERA_API_URL", "https://app.divera247.com/api/v2/pull/all")
    if not access_key:
        ctx = get_alarm_display({"success": True, "data": {"alarm": {"items": []}}})
        ctx["now"] = datetime.datetime.now()
        ctx["error"] = "DIVERA_ACCESS_KEY nicht konfiguriert"
        resp = render(request, "attendance/alarm.html", ctx)
        resp["Cache-Control"] = "no-store"
        return resp
    try:
        resp_api = requests.get(api_url, params={"accesskey": access_key, "access-key": access_key}, timeout=10)
        if resp_api.status_code != 200:
            ctx = get_alarm_display({"success": True, "data": {"alarm": {"items": []}}})
            ctx["now"] = datetime.datetime.now()
            ctx["error"] = "Daten nicht verfügbar"
            resp = render(request, "attendance/alarm.html", ctx)
            resp["Cache-Control"] = "no-store"
            return resp
        try:
            payload = resp_api.json()
        except ValueError:
            ctx = get_alarm_display({"success": True, "data": {"alarm": {"items": []}}})
            ctx["now"] = datetime.datetime.now()
            ctx["error"] = "Daten nicht verfügbar"
            resp = render(request, "attendance/alarm.html", ctx)
            resp["Cache-Control"] = "no-store"
            return resp
    except requests.RequestException:
        ctx = get_alarm_display({"success": True, "data": {"alarm": {"items": []}}})
        ctx["now"] = datetime.datetime.now()
        ctx["error"] = "Daten nicht verfügbar"
        resp = render(request, "attendance/alarm.html", ctx)
        resp["Cache-Control"] = "no-store"
        return resp
    ctx = get_alarm_display(payload)
    ctx["now"] = datetime.datetime.now()
    resp = render(request, "attendance/alarm.html", ctx)
    resp["Cache-Control"] = "no-store"
    return resp
