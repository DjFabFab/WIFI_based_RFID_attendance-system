from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from .models import Student, Log
from .uid_utils import preprocess_uid
import datetime


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
	if user.name is None:
		return 'profile saved'
	open_log = Log.objects.filter(
		card_id=user.card_id, time_out__isnull=True).order_by('id').first()
	if open_log:
		open_log.time_out = datetime.datetime.now()
		open_log.save()
		return 'logout'
	new_log = Log(ida=user.id, card_id=user.card_id, name=user.name, date=datetime.datetime.now(),
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
	return render(request, 'attendance/manage.html')


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
	selected_id = request.session.get('selected_card_id')
	if selected_id is None:
		messages.info(request, 'No Card was Selected')
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
