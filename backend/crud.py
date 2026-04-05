from datetime import datetime, timedelta
from sqlmodel import Session, select
from sqlalchemy import desc
from . import models
from . import auth as auth_module
from typing import List, Optional

# Use the shared engine exposed by models
ENGINE = models.ENGINE


# ---------- OAuth State CRUD (PKCE) ----------

def create_oauth_state(state: str, code_verifier: str, redirect_uri: str) -> models.OAuthState:
    """
    Store PKCE state for OAuth flow.
    
    Args:
        state: Random state string for CSRF protection
        code_verifier: PKCE code verifier to store
        redirect_uri: Original redirect URI from client
        
    Returns:
        Created OAuthState object
    """
    with Session(ENGINE) as sess:
        oauth_state = models.OAuthState(
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        sess.add(oauth_state)
        sess.commit()
        sess.refresh(oauth_state)
        return oauth_state


def get_and_delete_oauth_state(state: str) -> Optional[models.OAuthState]:
    """
    Retrieve and delete OAuth state (one-time use).
    Also cleans up expired states.
    
    Args:
        state: State string to look up
        
    Returns:
        OAuthState if found and not expired, None otherwise
    """
    with Session(ENGINE) as sess:
        # Get the state
        oauth_state = sess.get(models.OAuthState, state)
        
        if oauth_state:
            # Check if expired (10 minutes)
            age = datetime.utcnow() - oauth_state.created_at
            if age > timedelta(minutes=10):
                sess.delete(oauth_state)
                sess.commit()
                return None
            
            # Delete after retrieval (one-time use)
            sess.delete(oauth_state)
            sess.commit()
            
            # Return detached copy
            return models.OAuthState(
                state=oauth_state.state,
                code_verifier=oauth_state.code_verifier,
                redirect_uri=oauth_state.redirect_uri,
                created_at=oauth_state.created_at,
            )
        
        return None


def cleanup_expired_oauth_states(max_age_minutes: int = 10) -> int:
    """
    Delete expired OAuth states.
    
    Args:
        max_age_minutes: Maximum age in minutes before state expires
        
    Returns:
        Number of deleted states
    """
    with Session(ENGINE) as sess:
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        stmt = select(models.OAuthState).where(models.OAuthState.created_at < cutoff)
        expired = sess.exec(stmt).all()
        count = len(expired)
        for state in expired:
            sess.delete(state)
        sess.commit()
        return count


# ---------- User CRUD ----------

def get_user_by_oauth_id(oauth_id: str) -> Optional[models.User]:
    """
    Find user by OAuth subject ID.
    
    Args:
        oauth_id: OAuth subject ID (sub claim)
        
    Returns:
        User if found, None otherwise
    """
    with Session(ENGINE) as sess:
        stmt = select(models.User).where(models.User.oauth_id == oauth_id)
        return sess.exec(stmt).first()


def get_or_create_user(user_info: dict) -> models.User:
    """
    Get existing user or create new one from OAuth user info.
    
    Maps IITD OAuth claims to User model fields:
    - sub -> oauth_id
    - email -> email
    - name -> name
    - hostel -> hostel
    - entry_number -> entry_number, kerberos (derived)
    - department -> department
    - category -> category
    
    Args:
        user_info: Dictionary with OAuth claims
        
    Returns:
        User object (existing or newly created)
    """
    with Session(ENGINE) as sess:
        # First try to find by oauth_id (sub claim)
        oauth_id = user_info.get("sub")
        if oauth_id:
            stmt = select(models.User).where(models.User.oauth_id == oauth_id)
            res = sess.exec(stmt).first()
            if res:
                # Update existing user with latest info
                res.name = user_info.get("name") or res.name
                res.email = user_info.get("email") or res.email
                res.hostel = user_info.get("hostel") or res.hostel
                res.entry_number = user_info.get("entry_number") or res.entry_number
                res.department = user_info.get("department") or res.department
                res.category = user_info.get("category") or res.category
                # Derive kerberos from entry_number
                if res.entry_number:
                    res.kerberos = auth_module.entry_number_to_kerberos(res.entry_number)
                sess.add(res)
                sess.commit()
                sess.refresh(res)
                return res
        
        # Try to find by email as fallback
        email = user_info.get("email")
        if email:
            stmt = select(models.User).where(models.User.email == email)
            res = sess.exec(stmt).first()
            if res:
                # Update existing user
                res.oauth_id = oauth_id or res.oauth_id
                res.name = user_info.get("name") or res.name
                res.hostel = user_info.get("hostel") or res.hostel
                res.entry_number = user_info.get("entry_number") or res.entry_number
                res.department = user_info.get("department") or res.department
                res.category = user_info.get("category") or res.category
                if res.entry_number:
                    res.kerberos = auth_module.entry_number_to_kerberos(res.entry_number)
                sess.add(res)
                sess.commit()
                sess.refresh(res)
                return res
        
        # Create new user
        if not email:
            raise ValueError("user_info must contain an email")
        
        entry_number = user_info.get("entry_number")
        kerberos = auth_module.entry_number_to_kerberos(entry_number) if entry_number else None
        
        user = models.User(
            oauth_id=oauth_id,
            email=email,
            name=user_info.get("name"),
            picture=user_info.get("picture"),
            hostel=user_info.get("hostel"),
            kerberos=kerberos,
            entry_number=entry_number,
            department=user_info.get("department"),
            category=user_info.get("category"),
        )
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        return user


def create_chat(user_id: int, title: str | None = None) -> models.Chat:
    with Session(ENGINE) as sess:
        chat = models.Chat(user_id=user_id, title=title)
        sess.add(chat)
        sess.commit()
        sess.refresh(chat)
        return chat


def list_chats(user_id: int) -> List[models.Chat]:
    with Session(ENGINE) as sess:
        stmt = select(models.Chat).where(models.Chat.user_id == user_id).order_by(desc(models.Chat.created_at)) # type: ignore
        return list(sess.exec(stmt).all())


def get_chat(chat_id: int) -> Optional[models.Chat]:
    with Session(ENGINE) as sess:
        return sess.get(models.Chat, chat_id)


def create_message(chat_id: int, sender: str, content: str) -> models.Message:
    with Session(ENGINE) as sess:
        msg = models.Message(chat_id=chat_id, sender=sender, content=content)
        sess.add(msg)
        sess.commit()
        sess.refresh(msg)
        return msg


def list_messages(chat_id: int) -> List[models.Message]:
    with Session(ENGINE) as sess:
        stmt = select(models.Message).where(models.Message.chat_id == chat_id).order_by(models.Message.created_at) # type: ignore
        return list(sess.exec(stmt).all())

def delete_chat(chat_id: int) -> None:
    with Session(ENGINE) as sess:
        # Delete messages in bulk
        stmt_msgs = select(models.Message).where(models.Message.chat_id == chat_id)
        messages = sess.exec(stmt_msgs).all()
        for msg in messages:
            sess.delete(msg)

        # Delete chat
        chat = sess.get(models.Chat, chat_id)
        if chat:
            sess.delete(chat)

        sess.commit()


# ---------- Document CRUD ----------

def create_document(
    filename: str,
    original_name: str,
    description: str,
    file_size: int,
    chunk_count: int,
    uploaded_by: int,
) -> models.Document:
    with Session(ENGINE) as sess:
        doc = models.Document(
            filename=filename,
            original_name=original_name,
            description=description,
            file_size=file_size,
            chunk_count=chunk_count,
            uploaded_by=uploaded_by,
        )
        sess.add(doc)
        sess.commit()
        sess.refresh(doc)
        return doc


def list_documents() -> List[models.Document]:
    with Session(ENGINE) as sess:
        stmt = select(models.Document).order_by(desc(models.Document.created_at))  # type: ignore
        return list(sess.exec(stmt).all())


def get_document(doc_id: int) -> Optional[models.Document]:
    with Session(ENGINE) as sess:
        return sess.get(models.Document, doc_id)


def delete_document(doc_id: int) -> None:
    with Session(ENGINE) as sess:
        doc = sess.get(models.Document, doc_id)
        if doc:
            sess.delete(doc)
            sess.commit()
