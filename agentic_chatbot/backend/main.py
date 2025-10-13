from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from . import models, crud, schemas, auth

app = FastAPI(title="IITD Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP bearer handled in auth.get_current_user


@app.on_event("startup")
def on_startup():
    models.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(token: schemas.OIDCToken):
    # Verify the provided id_token with Google (or other IdP)
    user_info = auth.verify_id_token(token.id_token)
    if not user_info:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = crud.get_or_create_user(user_info)
    access_token = auth.create_access_token({"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/chats", response_model=schemas.ChatRead)
def create_chat(request: schemas.ChatCreate, current_user: models.User = Depends(auth.get_current_user)):
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    chat = crud.create_chat(user_id, request.title)
    return chat


@app.get("/chats", response_model=list[schemas.ChatRead])
def list_chats(current_user: models.User = Depends(auth.get_current_user)):
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    return crud.list_chats(user_id)


@app.get("/chats/{chat_id}", response_model=schemas.ChatRead)
def get_chat(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.post("/chats/{chat_id}/messages", response_model=schemas.MessageRead)
def send_message(chat_id: int, message: schemas.MessageCreate, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    # store user message
    crud.create_message(chat_id=chat_id, sender="user", content=message.content)

    # Call the agent from the existing package
    from agent import invoke_memory_agent

    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat_id))
        assistant_text = response.get('output') if isinstance(response, dict) else str(response)
        if assistant_text is None:
            assistant_text = ""
    except Exception as e:
        # Log the exception (print for now). In production, integrate structured logging.
        print("Agent invocation failed:", e)
        raise HTTPException(status_code=502, detail="Agent failed to respond")

    assistant_msg = crud.create_message(chat_id=chat_id, sender="assistant", content=assistant_text)
    return assistant_msg


@app.get("/chats/{chat_id}/messages", response_model=list[schemas.MessageRead])
def get_messages(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)
