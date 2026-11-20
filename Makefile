# ShelfReady — one-command workflows.
.PHONY: install data featured build eval run docker clean demo help

install:            ## install python deps
	pip install -r backend/requirements.txt

data:               ## generate synthetic catalogue + run pipeline bundle
	python catalog/generate_catalog.py
	python generator/export_bundle.py

featured:           ## run REAL Claude-CLI generations for the featured strip (needs `claude`)
	python generator/featured.py
	python generator/export_bundle.py

build:              ## build the standalone interactive demo
	python frontend/build.py

eval:               ## score the pipeline against the ground-truth answer key
	python -m backend.evaluate

run:                ## serve the API + demo at http://localhost:8000
	uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

demo: data build    ## regenerate everything and build the demo
	@echo "Open frontend/shelfready-demo-standalone.html in a browser."

docker:             ## build + run via docker compose
	docker compose up --build

clean:              ## remove generated demo files (cross-platform)
	python -c "import glob,os; [os.remove(f) for f in ['data/demo_data.json']+glob.glob('frontend/shelfready-demo*.html') if os.path.exists(f)]"

help:               ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n",$$1,$$2}'
