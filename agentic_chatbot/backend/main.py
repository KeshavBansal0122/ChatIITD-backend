from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from agent import invoke_memory_agent

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


@app.post("/auth/callback", response_model=schemas.TokenResponse)
async def auth_callback(payload: schemas.OAuthCallbackRequest):
    """OAuth callback endpoint for DevClub authentication."""
    code = payload.code
    state = payload.state

    # Validate incoming parameters
    print("Auth callback received code:", code, "state:", state)
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state in the request"
        )
    
    # Verify the authorization code with DevClub OAuth server
    user_info = await auth.verify_devclub_code(code, state)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error during authentication"
        )
    
    # Get or create user in database
    user = crud.get_or_create_user(user_info)
    print("Authenticated user:", user)
    
    # Create JWT access token
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


@app.post("/chats/new", response_model=schemas.NewChatResponse)
def create_new_chat_with_message(message: schemas.MessageCreate, current_user: models.User = Depends(auth.get_current_user)):
    """
    Create a new chat and send the first message.
    Returns the chat, the assistant's response, and the chat title.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    
    # Hardcoded title for now - do a call to return one later
    title_text = "Chat Title"
    
    # Create the chat with the title
    chat = crud.create_chat(user_id, title_text)
    
    if chat.id is None:
        raise HTTPException(status_code=500, detail="Failed to create chat")
    
    # Store user message
    crud.create_message(chat_id=chat.id, sender="user", content=message.content)
    
    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat.id))
        assistant_text = response.get('output') if isinstance(response, dict) else str(response)
        if assistant_text is None:
            assistant_text = ""
    except Exception as e:
        # Log the exception (print for now). In production, integrate structured logging.
        print("Agent invocation failed:", e)
        raise HTTPException(status_code=502, detail="Agent failed to respond")
    
    assistant_msg = crud.create_message(chat_id=chat.id, sender="assistant", content=assistant_text)
    
    return {
        "chat": chat,
        "message": assistant_msg,
        "title": title_text
    }



@app.post("/chats/{chat_id}/messages", response_model=schemas.MessageRead)
def send_message(chat_id: int, message: schemas.MessageCreate, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    # store user message
    crud.create_message(chat_id=chat_id, sender="user", content=message.content)


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

@app.delete("/chats/{chat_id}", status_code=204)
def delete_chat_endpoint(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    crud.delete_chat(chat_id)
    return {"detail": "Chat deleted"}