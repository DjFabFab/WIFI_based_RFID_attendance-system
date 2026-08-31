from .models import Student


def add_user(number):
	if number <= 0:
		return
	first = Student.objects.order_by('-card_id').first()
	max_id = first.card_id if first else 0
	start_id = max_id + 1
	Student.objects.bulk_create([Student(card_id=start_id+i) for i in range(number)])
