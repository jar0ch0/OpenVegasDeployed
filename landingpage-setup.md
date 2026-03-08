# Landing Page Setup

`landing-page-inspo.md` is complete (full HTML/CSS structure, all 3 cards, footer, responsive breakpoints).

I implemented it as a real `/ui` page:

1. New landing page: [ui/index.html](/Users/stephenekwedike/Desktop/OpenVegas/ui/index.html)
2. Backend route serving it at `/ui` and `/ui/`: [server/main.py](/Users/stephenekwedike/Desktop/OpenVegas/server/main.py:82)

How to run locally:

```bash
cd /Users/stephenekwedike/Desktop/OpenVegas
pip install -e ".[server]"
uvicorn server.main:app --reload  # see if already running in the server terminal
```

Open:

[http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui)
