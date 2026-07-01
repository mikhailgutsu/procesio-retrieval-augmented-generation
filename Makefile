.PHONY: install
install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt


.PHONY: run
run:
	.venv/bin/python main.py
