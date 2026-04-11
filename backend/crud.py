from datetime import datetime, timedelta
from sqlmodel import select
from sqlalchemy import desc
from . import models
from . import auth as auth_module
from . import courses_db
from .models import get_session
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


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
    with get_session() as sess:
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
    with get_session() as sess:
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
    with get_session() as sess:
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
    with get_session() as sess:
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
    with get_session() as sess:
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
                if res.email:
                    res.kerberos = auth_module.email_to_kerberos(res.email)
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
                if res.email:
                    res.kerberos = auth_module.email_to_kerberos(email)
                sess.add(res)
                sess.commit()
                sess.refresh(res)
                return res
        
        # Create new user
        if not email:
            raise ValueError("user_info must contain an email")
        
        entry_number = user_info.get("entry_number")
        kerberos = auth_module.email_to_kerberos(email) if email else None
        
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
    logger.info(f"[CREATE_CHAT] user_id={user_id}, title={title}")
    with get_session() as sess:
        chat = models.Chat(user_id=user_id, title=title)
        sess.add(chat)
        sess.commit()
        sess.refresh(chat)
        logger.info(f"[CREATE_CHAT] Created chat with id={chat.id}")
        return chat


def list_chats(user_id: int) -> List[models.Chat]:
    with get_session() as sess:
        stmt = select(models.Chat).where(models.Chat.user_id == user_id).order_by(desc(models.Chat.created_at)) # type: ignore
        return list(sess.exec(stmt).all())


def get_chat(chat_id: int) -> Optional[models.Chat]:
    with get_session() as sess:
        return sess.get(models.Chat, chat_id)


def create_message(chat_id: int, sender: str, content: str) -> models.Message:
    with get_session() as sess:
        msg = models.Message(chat_id=chat_id, sender=sender, content=content)
        sess.add(msg)
        sess.commit()
        sess.refresh(msg)
        return msg


def list_messages(chat_id: int) -> List[models.Message]:
    with get_session() as sess:
        stmt = select(models.Message).where(models.Message.chat_id == chat_id).order_by(models.Message.created_at) # type: ignore
        return list(sess.exec(stmt).all())

def delete_chat(chat_id: int) -> None:
    with get_session() as sess:
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
    with get_session() as sess:
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
    with get_session() as sess:
        stmt = select(models.Document).order_by(desc(models.Document.created_at))  # type: ignore
        return list(sess.exec(stmt).all())


def get_document(doc_id: int) -> Optional[models.Document]:
    with get_session() as sess:
        return sess.get(models.Document, doc_id)


def delete_document(doc_id: int) -> None:
    with get_session() as sess:
        doc = sess.get(models.Document, doc_id)
        if doc:
            sess.delete(doc)
            sess.commit()


# ---------- User Course CRUD ----------

def validate_course_code(course_code: str) -> bool:
    """
    Validate that a course code exists in the courses database.
    
    Args:
        course_code: Course code to validate (e.g., "COL100")
        
    Returns:
        True if course exists, False otherwise
    """
    return courses_db.validate_course_code(course_code)


def search_courses_by_prefix(prefix: str, limit: int = 20) -> List[Dict]:
    """
    Search courses by code prefix for autocomplete.
    
    Args:
        prefix: Course code prefix (e.g., "COL")
        limit: Maximum results to return
        
    Returns:
        List of course dicts with code and name
    """
    return courses_db.search_courses_by_prefix(prefix, limit)


def get_user_courses(user_id: int) -> Dict[int, List[str]]:
    """
    Get all courses for a user, grouped by semester.
    
    Args:
        user_id: User ID
        
    Returns:
        Dict mapping semester number to list of course codes
    """
    with get_session() as sess:
        stmt = select(models.UserCourse).where(models.UserCourse.user_id == user_id).order_by(models.UserCourse.semester)
        user_courses = sess.exec(stmt).all()
        
        result: Dict[int, List[str]] = {}
        for uc in user_courses:
            if uc.semester not in result:
                result[uc.semester] = []
            result[uc.semester].append(uc.course_code)
        
        return result


def add_user_course(user_id: int, course_code: str, semester: int) -> Optional[models.UserCourse]:
    """
    Add a course for a user in a specific semester.
    
    Args:
        user_id: User ID
        course_code: Course code (will be uppercased)
        semester: Semester number (1-10)
        
    Returns:
        Created UserCourse if successful, None if course already exists or invalid
    """
    course_code = course_code.upper().strip()
    
    with get_session() as sess:
        # Check if already exists
        stmt = select(models.UserCourse).where(
            models.UserCourse.user_id == user_id,
            models.UserCourse.course_code == course_code,
            models.UserCourse.semester == semester
        )
        existing = sess.exec(stmt).first()
        if existing:
            return None  # Already exists
        
        user_course = models.UserCourse(
            user_id=user_id,
            course_code=course_code,
            semester=semester
        )
        sess.add(user_course)
        sess.commit()
        sess.refresh(user_course)
        return user_course


def remove_user_course(user_id: int, course_code: str, semester: int) -> bool:
    """
    Remove a course for a user from a specific semester.
    
    Args:
        user_id: User ID
        course_code: Course code
        semester: Semester number
        
    Returns:
        True if removed, False if not found
    """
    course_code = course_code.upper().strip()
    
    with get_session() as sess:
        stmt = select(models.UserCourse).where(
            models.UserCourse.user_id == user_id,
            models.UserCourse.course_code == course_code,
            models.UserCourse.semester == semester
        )
        user_course = sess.exec(stmt).first()
        if user_course:
            sess.delete(user_course)
            sess.commit()
            return True
        return False


def set_user_courses(user_id: int, courses_by_semester: Dict[int, List[str]]) -> Dict[int, List[str]]:
    """
    Bulk set courses for a user, replacing all existing courses.
    
    Args:
        user_id: User ID
        courses_by_semester: Dict mapping semester number to list of course codes
        
    Returns:
        The courses that were actually saved (after validation)
    """
    with get_session() as sess:
        # Delete all existing courses for this user
        stmt = select(models.UserCourse).where(models.UserCourse.user_id == user_id)
        existing = sess.exec(stmt).all()
        for uc in existing:
            sess.delete(uc)
        
        # Add new courses
        saved: Dict[int, List[str]] = {}
        for semester, course_codes in courses_by_semester.items():
            saved[semester] = []
            for code in course_codes:
                code = code.upper().strip()
                if code:  # Skip empty strings
                    user_course = models.UserCourse(
                        user_id=user_id,
                        course_code=code,
                        semester=semester
                    )
                    sess.add(user_course)
                    saved[semester].append(code)
        
        sess.commit()
        return saved
