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
        group_map = {}
        for k in ("cluster", "clusters", "group", "groups", "ucr"):
            g = data.get(k)
            if isinstance(g, dict) and g:
                if not group_map:
                    group_map = {}
                group_map.update(g)

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

        # --- Personnel status: counts per Divera status (only ucr_answered / alarm state) ---
        # and role breakdown AGT/MA/GF. Only count statuses that were changed after alarm.
        status_counts = {}
        role_counts = {"AGT": 0, "MA": 0, "GF": 0}
        try:
            # 1. status counts: prefer selected alarm's ucr_answered / participants if present
            candidate_status = None
            for k in ("ucr_answered", "ucrAnswered", "responses", "participants", "attendees", "status_counts", "statusCounts"):
                if k in selected and isinstance(selected[k], dict):
                    candidate_status = selected[k]
                    break
            # fallback: data-level monitor filtered to alarm-relevant statuses
            if candidate_status is None:
                # check data-level keys that may hold per-alarm status
                for dk in ("ucr_answered", "responses"):
                    dv = data.get(dk)
                    if isinstance(dv, dict) and dv:
                        candidate_status = dv
                        break
            if isinstance(candidate_status, dict) and candidate_status:
                for sid, users in candidate_status.items():
                    try:
                        # users may be dict of user->status or list
                        if isinstance(users, dict):
                            cnt = len(users)
                        elif isinstance(users, list):
                            cnt = len(users)
                        elif isinstance(users, int):
                            cnt = users
                        else:
                            cnt = 1
                        # only include if count >0 (changed after alarm)
                        if cnt > 0:
                            status_counts[str(sid)] = cnt
                    except Exception:
                        continue
            # 2. role counts: check qualifications in data.cluster / data.user
            # load configurable mapping for AGT/MA/GF qualification IDs
            default_role_map = {"AGT": [58, 22356], "MA": [62, 2], "GF": [3, 4]}
            role_map = dict(default_role_map)
            try:
                # try deployment/alarm_roles.json relative to project
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
            # collect users who responded (flatten candidate_status)
            responded_user_ids = set()
            if isinstance(candidate_status, dict):
                for users in candidate_status.values():
                    if isinstance(users, dict):
                        for uid in users.keys():
                            responded_user_ids.add(str(uid))
                    elif isinstance(users, list):
                        for uid in users:
                            responded_user_ids.add(str(uid))
            # if we have responded users, check their qualifications in cluster
            if responded_user_ids:
                # cluster holds user details with qualifications
                cluster_map = {}
                for ck in ("cluster", "users", "user"):
                    cm = data.get(ck)
                    if isinstance(cm, dict) and cm:
                        cluster_map.update(cm)
                # lookup
                for uid in responded_user_ids:
                    uinfo = cluster_map.get(uid) or cluster_map.get(int(uid)) if uid.isdigit() else None
                    if not isinstance(uinfo, dict):
                        # try str key
                        uinfo = cluster_map.get(str(uid))
                    if not isinstance(uinfo, dict):
                        continue
                    quals = uinfo.get("qualifications") or uinfo.get("quals") or uinfo.get("roles") or []
                    if not isinstance(quals, list):
                        continue
                    qset = set()
                    for q in quals:
                        try:
                            qset.add(int(q))
                        except Exception:
                            continue
                    for role, qids in role_map.items():
                        if any(q in qset for q in qids):
                            role_counts[role] += 1
            else:
                # no responded users -> try to infer from monitor qualification totals, but only if active
                # keep role_counts as 0 to avoid misleading
                pass
        except Exception:
            status_counts = {}
            role_counts = {"AGT": 0, "MA": 0, "GF": 0}

        crew_list = []
        role_names = {"AGT": [], "MA": [], "GF": []}
        try:
            _color_map_for_names = {}
            try:
                default_color_map2 = {"78645": "success", "78647": "warning", "78646": "primary", "78650": "info"}
                for p in [pathlib.Path(__file__).resolve().parent.parent / "deployment" / "alarm_status.json",
                          pathlib.Path(settings.BASE_DIR) / "deployment" / "alarm_status.json"]:
                    if p.exists():
                        jm = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(jm, dict):
                            default_color_map2.update({str(k): str(v) for k, v in jm.items()})
                        break
                _color_map_for_names = default_color_map2
            except Exception:
                _color_map_for_names = {"78645": "success", "78647": "warning", "78646": "primary", "78650": "info"}

            _role_map2 = {"AGT": [58, 22356], "MA": [62, 2], "GF": [3, 4]}
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

            _cluster = {}
            for ck in ("cluster", "users", "user"):
                cm = data.get(ck)
                if isinstance(cm, dict) and cm:
                    _cluster.update(cm)

            _user_status = {}
            if isinstance(candidate_status, dict):
                for sid, users in candidate_status.items():
                    sid_str = str(sid)
                    if isinstance(users, dict):
                        for uid in users.keys():
                            _user_status[str(uid)] = sid_str
                    elif isinstance(users, list):
                        for uid in users:
                            _user_status[str(uid)] = sid_str

            for uid in responded_user_ids:
                uid_str = str(uid)
                name = uid_str
                uinfo = _cluster.get(uid_str)
                if not isinstance(uinfo, dict):
                    try:
                        uinfo = _cluster.get(int(uid_str))
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
                if color in ("success", "primary", "info"):
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
                                    role_names[role].append(name)
            # sort: green -> blue -> info -> yellow -> rest
            _color_order = {"success": 0, "primary": 1, "info": 2, "warning": 3, "secondary": 4}
            crew_list.sort(key=lambda x: (_color_order.get(x["color"], 5), x["name"]))
        except Exception:
            crew_list = []
            role_names = {"AGT": [], "MA": [], "GF": []}

        # map status IDs

        # map status IDs to display labels/colors for kiosk (green/blue/yellow)
        # default: known Divera statuses -> colors, fallback to hash
        status_display = []
        color_map = {}
        try:
            # try to load status color mapping
            default_color_map = {"78645": "success", "78647": "warning", "78646": "primary", "78650": "info"}
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
            color_map = {"78645": "success", "78647": "warning", "78646": "primary"}
        for sid, cnt in status_counts.items():
            label = sid
            # try to resolve name from ucr/cluster if available
            try:
                # ucr map may have name
                ucr_map = data.get("ucr") or data.get("cluster") or {}
                if isinstance(ucr_map, dict):
                    info = ucr_map.get(sid) or ucr_map.get(str(sid))
                    if isinstance(info, dict):
                        label = info.get("name") or info.get("title") or info.get("label") or sid
                    elif isinstance(info, str):
                        label = info
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
            status_display.append({"id": sid, "label": str(label), "count": cnt, "color": color})

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


def search(request):
	search_id = request.GET.get('search') or request.POST.get('search')
	if search_id:
		try:
			search_id = int(search_id)
		except (TypeError, ValueError):
			search_id = None
		sel_user = Student.objects.filter(id=search_id).first() if search_id else None
		logf = Log.objects.filter(
			ida=search_id,
			date__year=datetime.date.today().year,
			date__month=datetime.date.today().month,
		).order_by('-id') if search_id else Log.objects.none()
		dataset = {'use': sel_user, 'log': logf}
		return render(request, 'attendance/search.html', dataset)
	else:
		return redirect('/home')


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
