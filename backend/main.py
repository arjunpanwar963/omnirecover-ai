from fastapi import FastAPI, HTTPException
from backend.engine import OmniRecoverEngine

app = FastAPI(title="OmniRecover AI Engine API", version="1.0.0")
engine = OmniRecoverEngine()

@app.get("/")
def read_root():
    return {"message": "OmniRecover AI Agent Engine is Online"}

@app.post("/api/v1/recovery/run-batch")
def run_batch():
    try:
        summary = engine.run_batch_recovery()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))