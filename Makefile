run :
	python manage.py runserver

run_uvicorn :
	uvicorn mysite.asgi:application

docker_build :
	docker build -t channels_bug:latest .

docker_run :
	docker run -it --rm -p 8000:8000 channels_bug:latest

.PHONY : run run_uvicorn docker_build docker_run

