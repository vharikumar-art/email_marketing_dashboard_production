from fastapi import FastAPI, Form, File, UploadFile
import uvicorn
from pydantic import BaseModel
from typing import Annotated

app = FastAPI()

class DummyModel(BaseModel):
    name: str
    age: int

@app.post("/test")
async def test_endpoint(
    data: Annotated[DummyModel, Form()],
    file: UploadFile = File(...)
):
    return {"name": data.name, "age": data.age, "filename": file.filename}

if __name__ == "__main__":
    uvicorn.run(app, port=8001)
