import asyncio
from fastapi import FastAPI, Request, UploadFile
from fastapi.testclient import TestClient

app = FastAPI()

@app.post("/test")
async def test(request: Request):
    form = await request.form()
    print("Form items:")
    for k, v in form.items():
        print(f"k: {k}, type(v): {type(v)}, hasattr(v, 'read'): {hasattr(v, 'read')}")
        if hasattr(v, 'filename'):
            print(f"  filename: {v.filename}")
    return {"ok": True}

client = TestClient(app)
with open("../../2025 封存文件夹/截图/2023图片/50258ed151d7b3fd46b6dbdad56b65cd.jpg", "rb") as f:
    res = client.post("/test", data={"info": '{"global_info": {}}'}, files={"alarm_picture_0.jpg": f})
    print(res.json())
