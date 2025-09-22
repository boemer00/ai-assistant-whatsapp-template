PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8001 --reload

ngrok http 8001

curl -s http://127.0.0.1:8001/health
