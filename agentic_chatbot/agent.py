"""
IIT Delhi Academic Chatbot Agent using OpenRouter.

This module provides the agent functionality for the chatbot using OpenRouter's API
with the OpenAI SDK. It implements a ReAct-style agent with tool calling capabilities.
"""

import os
import json
from typing import AsyncGenerator
from pathlib import Path
from openai import OpenAI, AsyncOpenAI, PermissionDeniedError, AuthenticationError, RateLimitError, APITimeoutError, BadRequestError, APIStatusError
from dotenv import load_dotenv

from .tools import TOOLS, TOOL_MAPPING, execute_tool

# Import logging from backend if available, otherwise use standard logging
try:
    from backend.logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


# Load environment variables from a .env file
load_dotenv('../.env')
load_dotenv('.env')


# =====================
# Error Classification
# =====================

def classify_openrouter_error(e: Exception) -> dict:
    """
    Classify an OpenRouter/OpenAI API exception into a structured error event
    with a user-friendly message and a stable error_code.
    
    Returns a dict suitable for yielding as a WebSocket error event:
    {"type": "error", "message": "...", "error_code": "..."}
    """
    # Try to extract HTTP status code from the exception
    status_code = None
    if isinstance(e, APIStatusError):
        status_code = e.status_code
    
    # Also check the error body for OpenRouter-style {"error": {"code": N}}
    if status_code is None and hasattr(e, 'body') and isinstance(e.body, dict):
        status_code = e.body.get('error', {}).get('code')

    error_map = {
        400: ("bad_request", "The request was invalid. Please try again."),
        401: ("unauthorized", "API authentication failed. Please contact the administrator."),
        402: ("insufficient_credits", "The AI service has run out of credits. Please contact the administrator."),
        403: ("forbidden", "The AI service key limit has been exceeded. Please contact the administrator."),
        408: ("timeout", "The AI service timed out. Please try again."),
        429: ("rate_limited", "Too many requests to the AI service. Please wait a moment and try again."),
        502: ("model_unavailable", "The AI model is currently unavailable. Please try again later."),
        503: ("service_unavailable", "The AI service is unavailable. Please try again later."),
    }

    if status_code in error_map:
        error_code, message = error_map[status_code]
    elif isinstance(e, AuthenticationError):
        error_code, message = "unauthorized", "API authentication failed. Please contact the administrator."
    elif isinstance(e, PermissionDeniedError):
        error_code, message = "forbidden", "The AI service key limit has been exceeded. Please contact the administrator."
    elif isinstance(e, RateLimitError):
        error_code, message = "rate_limited", "Too many requests to the AI service. Please wait a moment and try again."
    elif isinstance(e, APITimeoutError):
        error_code, message = "timeout", "The AI service timed out. Please try again."
    elif isinstance(e, BadRequestError):
        error_code, message = "bad_request", "The request was invalid. Please try again."
    else:
        error_code, message = "api_error", "An unexpected error occurred with the AI service. Please try again."

    return {"type": "error", "message": message, "error_code": error_code}


# =====================
# Configuration
# =====================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
MAX_TOOL_ITERATIONS = 30

logger.info(f"OpenRouter API Key configured: {'Yes' if OPENROUTER_API_KEY else 'NO - MISSING!'}")
logger.info(f"Using model: {MODEL}")

# Initialize OpenRouter clients (using OpenAI SDK with custom base URL)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

async_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)


# =====================
# System Prompt
# =====================

# Load the base system prompt
_AGENT_DIR = Path(__file__).resolve().parent
with open(_AGENT_DIR / 'system_prompt.txt', 'r') as file:
    BASE_SYSTEM_PROMPT = file.read()


def build_system_prompt(user_context: dict | None = None) -> str:
    """Build the system prompt with optional user context."""
    prompt = BASE_SYSTEM_PROMPT
    
    if user_context:
        user_info_parts = []
        if user_context.get("name"):
            user_info_parts.append(f"Name: {user_context['name']}")
        if user_context.get("email"):
            user_info_parts.append(f"Email: {user_context['email']}")
        if user_context.get("kerberos"):
            user_info_parts.append(f"Kerberos ID: {user_context['kerberos']}")
        if user_context.get("programme_code"):
            user_info_parts.append(f"Programme Code: {user_context['programme_code']}")
        if user_context.get("programme_name"):
            user_info_parts.append(f"Programme: {user_context['programme_name']}")
        if user_context.get("year_of_joining"):
            user_info_parts.append(f"Year of Joining: {user_context['year_of_joining']}")
        if user_context.get("hostel"):
            user_info_parts.append(f"Hostel: {user_context['hostel']}")
        if user_context.get("courses_done"):
            user_info_parts.append(f"Courses Done: {json.dumps(user_context['courses_done'])}")
        
        if user_info_parts:
            user_context_section = "\n\n---\n\n## **User Context**\n\nYou are currently assisting the following user:\n" + "\n".join(f"- {part}" for part in user_info_parts)
            prompt += user_context_section
    
    return prompt


# =====================
# Chat History Management (via central database)
# =====================

def get_chat_history(session_id: str) -> list[dict]:
    """Retrieve chat history for a session from the central database."""
    from backend.models import MessageHistory, get_session
    from sqlmodel import select
    
    logger.info(f"[GET_CHAT_HISTORY] Retrieving history for session_id={session_id}")
    
    messages = []
    with get_session() as session:
        statement = select(MessageHistory).where(
            MessageHistory.session_id == session_id
        ).order_by(MessageHistory.created_at)
        
        results = session.exec(statement).all()
        
        for row in results:
            message = {"role": row.role}
            
            if row.content is not None:
                message["content"] = row.content
            
            if row.tool_calls:
                message["tool_calls"] = json.loads(row.tool_calls)
                # For assistant messages with tool_calls, content should be null or omitted
                if row.role == "assistant" and not row.content:
                    message["content"] = None
            
            if row.tool_call_id:
                message["tool_call_id"] = row.tool_call_id
            
            if row.name:
                message["name"] = row.name
                
            messages.append(message)
    
    logger.info(f"[GET_CHAT_HISTORY] Retrieved {len(messages)} messages for session_id={session_id}")
    return messages


def add_message_to_history(session_id: str, message: dict):
    """Add a message to the chat history in the central database."""
    from backend.models import MessageHistory, get_session
    
    tool_calls_json = None
    if "tool_calls" in message:
        # Convert tool_calls to a serializable format
        tool_calls = []
        for tc in message["tool_calls"]:
            if hasattr(tc, 'model_dump'):
                tool_calls.append(tc.model_dump())
            elif hasattr(tc, '__dict__'):
                # Handle OpenAI SDK objects
                tc_dict = {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                tool_calls.append(tc_dict)
            else:
                tool_calls.append(tc)
        tool_calls_json = json.dumps(tool_calls)
    
    with get_session() as session:
        history_entry = MessageHistory(
            session_id=session_id,
            role=message.get("role"),
            content=message.get("content"),
            tool_calls=tool_calls_json,
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name")
        )
        session.add(history_entry)
        session.commit()


def clear_chat_history(session_id: str):
    """Clear chat history for a session."""
    from backend.models import MessageHistory, get_session
    from sqlmodel import delete
    
    with get_session() as session:
        statement = delete(MessageHistory).where(MessageHistory.session_id == session_id)
        session.exec(statement)
        session.commit()


# =====================
# Agent Core Functions
# =====================

def process_tool_calls(tool_calls) -> list[dict]:
    """
    Process tool calls from the model response and return tool results.
    """
    tool_messages = []
    
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            arguments = {}
        
        logger.info(f"[Tool Call] {tool_name}: {arguments}")
        
        # Execute the tool
        result = execute_tool(tool_name, arguments)
        
        logger.info(f"[Tool Result] {tool_name}: {result[:200]}..." if len(result) > 200 else f"[Tool Result] {tool_name}: {result}")
        
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        })
    
    return tool_messages


def invoke_memory_agent(input_dict: dict, session_id: str | None = None, user_context: dict | None = None) -> dict:
    """
    Invoke the agent with optional session history and user context.
    
    Args:
        input_dict: The input dictionary containing the user query under 'input' key
        session_id: Optional session ID for conversation history
        user_context: Optional user context dict with keys like 'name', 'email', 'kerberos', 'hostel'
    
    Returns:
        dict with 'output' key containing the agent's response
    """
    user_message = input_dict.get("input", "")
    logger.info(f"[invoke_memory_agent] Starting for session_id={session_id}, message: {user_message[:100]}...")
    
    system_prompt = build_system_prompt(user_context)
    
    # Build messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add chat history if session_id is provided
    if session_id:
        history = get_chat_history(session_id)
        logger.info(f"[invoke_memory_agent] Loaded {len(history)} messages from history")
        messages.extend(history)
    
    # Add the current user message
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    
    # Save user message to history
    if session_id:
        add_message_to_history(session_id, user_msg)
    
    logger.info(f"[invoke_memory_agent] Total messages in context: {len(messages)}")
    
    # Agentic loop with tool calling
    iteration = 0
    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        logger.info(f"[invoke_memory_agent] Iteration {iteration}/{MAX_TOOL_ITERATIONS}")
        
        try:
            logger.info(f"[invoke_memory_agent] Calling OpenRouter API with model: {MODEL}")
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                extra_headers={
                    "HTTP-Referer": "https://chatiitd.devclub.in",
                    "X-OpenRouter-Title": "ChatIITD Academic Assistant",
                }
            )
            logger.info(f"[invoke_memory_agent] Got response")
        except Exception as e:
            logger.error(f"[invoke_memory_agent] OpenRouter API call failed: {e}", exc_info=True)
            return {"output": f"Sorry, I encountered an error while processing your request: {str(e)}"}
        
        if not response.choices:
            logger.error("[invoke_memory_agent] No choices in response!")
            return {"output": "Sorry, I received an empty response from the AI service."}
        
        assistant_message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        
        logger.info(f"[invoke_memory_agent] Finish reason: {finish_reason}")
        logger.info(f"[invoke_memory_agent] Has tool_calls: {bool(assistant_message.tool_calls)}")
        logger.info(f"[invoke_memory_agent] Content: {assistant_message.content[:200] if assistant_message.content else 'None'}...")
        
        # Convert assistant message to dict for storage
        assistant_msg_dict = {
            "role": "assistant",
            "content": assistant_message.content
        }
        
        if assistant_message.tool_calls:
            assistant_msg_dict["tool_calls"] = assistant_message.tool_calls
        
        messages.append(assistant_msg_dict)
        
        # Check if we need to process tool calls
        if finish_reason == "tool_calls" or assistant_message.tool_calls:
            logger.info(f"[invoke_memory_agent] Processing {len(assistant_message.tool_calls)} tool calls")
            # Process tool calls
            tool_messages = process_tool_calls(assistant_message.tool_calls)
            messages.extend(tool_messages)
            
            # Save assistant message and tool results to history
            if session_id:
                add_message_to_history(session_id, assistant_msg_dict)
                for tool_msg in tool_messages:
                    add_message_to_history(session_id, tool_msg)
        else:
            # No more tool calls, we have the final response
            logger.info("[invoke_memory_agent] No tool calls, returning final response")
            if session_id:
                add_message_to_history(session_id, assistant_msg_dict)
            
            # Get content, fall back to reasoning if content is None
            final_content = assistant_message.content
            if final_content is None and hasattr(assistant_message, 'reasoning') and assistant_message.reasoning:
                logger.info("[invoke_memory_agent] Content is None, using reasoning field as fallback")
                final_content = assistant_message.reasoning
            
            return {"output": final_content or ""}
    
    # Max iterations reached
    logger.warning(f"[invoke_memory_agent] Maximum tool iterations ({MAX_TOOL_ITERATIONS}) reached")
    final_content = messages[-1].get("content") if isinstance(messages[-1], dict) else ""
    return {"output": final_content or "I apologize, but I couldn't complete the request within the allowed number of steps."}


async def stream_memory_agent(input_dict: dict, session_id: str | None = None, user_context: dict | None = None) -> AsyncGenerator[str, None]:
    """
    Stream the agent response token by token.
    
    Args:
        input_dict: The input dictionary containing the user query under 'input' key
        session_id: Optional session ID for conversation history
        user_context: Optional user context dict with keys like 'name', 'email', 'kerberos', 'hostel'
        
    Yields:
        Tokens of the agent's response as they are generated
    """
    user_message = input_dict.get("input", "")
    logger.info(f"[stream_memory_agent] Starting stream for message: {user_message[:100]}...")
    logger.info(f"[stream_memory_agent] Session ID: {session_id}")
    
    system_prompt = build_system_prompt(user_context)
    
    # Build messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add chat history if session_id is provided
    if session_id:
        history = get_chat_history(session_id)
        logger.info(f"[stream_memory_agent] Loaded {len(history)} messages from history")
        messages.extend(history)
    
    # Add the current user message
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    
    # Save user message to history
    if session_id:
        add_message_to_history(session_id, user_msg)
    
    logger.info(f"[stream_memory_agent] Total messages in context: {len(messages)}")
    
    # Agentic loop with tool calling
    iteration = 0
    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        logger.info(f"[stream_memory_agent] Iteration {iteration}/{MAX_TOOL_ITERATIONS}")
        
        try:
            logger.info(f"[stream_memory_agent] Calling OpenRouter API (non-streaming) with model: {MODEL}")
            # First, check if we need to do tool calls (non-streaming)
            response = await async_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                extra_headers={
                    "HTTP-Referer": "https://chatiitd.devclub.in",
                    "X-OpenRouter-Title": "ChatIITD Academic Assistant",
                }
            )
            logger.info(f"[stream_memory_agent] Got response: {response}")
        except Exception as e:
            logger.error(f"[stream_memory_agent] OpenRouter API call failed: {e}", exc_info=True)
            yield f"Sorry, I encountered an error while processing your request: {str(e)}"
            return
        
        if not response.choices:
            logger.error("[stream_memory_agent] No choices in response!")
            yield "Sorry, I received an empty response from the AI service."
            return
        
        assistant_message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        
        logger.info(f"[stream_memory_agent] Finish reason: {finish_reason}")
        logger.info(f"[stream_memory_agent] Has tool_calls: {bool(assistant_message.tool_calls)}")
        logger.info(f"[stream_memory_agent] Content: {assistant_message.content[:200] if assistant_message.content else 'None'}...")
        
        # Check if we need to process tool calls
        if finish_reason == "tool_calls" or assistant_message.tool_calls:
            logger.info(f"[stream_memory_agent] Processing {len(assistant_message.tool_calls)} tool calls")
            # Process tool calls (this is not streamed)
            assistant_msg_dict = {
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            }
            messages.append(assistant_msg_dict)
            
            tool_messages = process_tool_calls(assistant_message.tool_calls)
            messages.extend(tool_messages)
            
            # Save to history
            if session_id:
                add_message_to_history(session_id, assistant_msg_dict)
                for tool_msg in tool_messages:
                    add_message_to_history(session_id, tool_msg)
            
            # Continue the loop to get the next response
            continue
        else:
            # No tool calls - make a streaming call for the final response
            logger.info("[stream_memory_agent] No tool calls, making streaming call for final response")
            
            try:
                logger.info(f"[stream_memory_agent] Calling OpenRouter API (streaming) with model: {MODEL}")
                stream = await async_client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="none",  # Don't allow tools in final response
                    stream=True,
                    extra_headers={
                        "HTTP-Referer": "https://chatiitd.devclub.in",
                        "X-OpenRouter-Title": "ChatIITD Academic Assistant",
                    }
                )
                
                full_response = ""
                chunk_count = 0
                async for chunk in stream:
                    chunk_count += 1
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        yield content
                
                logger.info(f"[stream_memory_agent] Streaming complete. Received {chunk_count} chunks, total length: {len(full_response)}")
                
                # Save assistant message to history
                if session_id and full_response:
                    add_message_to_history(session_id, {
                        "role": "assistant",
                        "content": full_response
                    })
                
                if not full_response:
                    yield "I apologize, but I was unable to generate a response. Please try again."
                
            except Exception as e:
                logger.error(f"[stream_memory_agent] Streaming failed: {e}", exc_info=True)
                yield "Sorry, I encountered an error while streaming the response."
            
            return
    
    # Max iterations reached
    logger.warning(f"[stream_memory_agent] Maximum tool iterations ({MAX_TOOL_ITERATIONS}) reached")
    yield "I apologize, but I couldn't complete the request within the allowed number of steps."


def format_tool_status(tool_name: str, arguments: dict) -> str:
    """
    Format tool call status for display.
    Shows tool name and arguments if they're short enough.
    """
    # Format arguments for display (truncate if too long)
    args_str = ""
    if arguments:
        args_items = []
        for k, v in arguments.items():
            v_str = str(v)
            if len(v_str) > 50:
                v_str = v_str[:47] + "..."
            args_items.append(f"{k}={v_str}")
        args_str = ", ".join(args_items)
        if len(args_str) > 100:
            args_str = ""  # Skip arguments if too long
    
    if args_str:
        return f"{tool_name}({args_str})"
    return tool_name


async def stream_memory_agent_with_status(
    input_dict: dict, 
    session_id: str | None = None, 
    user_context: dict | None = None,
    cancel_event: "asyncio.Event | None" = None
) -> AsyncGenerator[dict, None]:
    """
    Stream the agent response with status events for WebSocket.
    
    Args:
        input_dict: The input dictionary containing the user query under 'input' key
        session_id: Optional session ID for conversation history
        user_context: Optional user context dict
        cancel_event: Optional asyncio.Event to signal cancellation
        
    Yields:
        Dict events with types: 'status', 'token', 'done', 'error'
        - status: { type: 'status', status: 'thinking' | 'tool_call', tool?: string }
        - token: { type: 'token', content: string }
        - done: { type: 'done' }
        - error: { type: 'error', message: string }
    """
    import asyncio
    
    user_message = input_dict.get("input", "")
    logger.info(f"[STREAM_AGENT] Starting for session_id={session_id}, message: {user_message[:100]}...")
    
    system_prompt = build_system_prompt(user_context)
    
    # Build messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add chat history if session_id is provided
    if session_id:
        history = get_chat_history(session_id)
        logger.info(f"[STREAM_AGENT] session_id={session_id}, loaded {len(history)} messages from history")
        messages.extend(history)
    
    # Add the current user message
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    
    # Save user message to history
    if session_id:
        add_message_to_history(session_id, user_msg)
    
    # Agentic loop with tool calling
    iteration = 0
    while iteration < MAX_TOOL_ITERATIONS:
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            logger.info("[stream_with_status] Cancelled by user")
            yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
            return
        
        iteration += 1
        logger.info(f"[stream_with_status] Iteration {iteration}/{MAX_TOOL_ITERATIONS}")
        
        # Emit thinking status
        yield {"type": "status", "status": "thinking"}
        
        try:
            response = await async_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                extra_headers={
                    "HTTP-Referer": "https://chatiitd.devclub.in",
                    "X-OpenRouter-Title": "ChatIITD Academic Assistant",
                }
            )
        except Exception as e:
            logger.error(f"[stream_with_status] API call failed: {e}", exc_info=True)
            yield classify_openrouter_error(e)
            return
        
        if not response.choices:
            yield {"type": "error", "message": "Empty response from AI service", "error_code": "empty_response"}
            return
        
        assistant_message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        
        logger.info(f"[stream_with_status] finish_reason={finish_reason}, has_tool_calls={bool(assistant_message.tool_calls)}, content_length={len(assistant_message.content) if assistant_message.content else 0}")
        
        # Check if we need to process tool calls
        if finish_reason == "tool_calls" or assistant_message.tool_calls:
            logger.info(f"[stream_with_status] Processing {len(assistant_message.tool_calls)} tool calls")
            
            assistant_msg_dict = {
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": assistant_message.tool_calls
            }
            messages.append(assistant_msg_dict)
            
            # Process each tool call with status updates
            tool_messages = []
            for tool_call in assistant_message.tool_calls:
                # Check for cancellation before each tool
                if cancel_event and cancel_event.is_set():
                    logger.info("[stream_with_status] Cancelled by user during tool calls")
                    yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
                    return
                
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}
                
                # Emit tool call status
                tool_display = format_tool_status(tool_name, arguments)
                yield {"type": "status", "status": "tool_call", "tool": tool_display}
                
                logger.info(f"[Tool Call] {tool_name}: {arguments}")
                
                # Execute the tool
                result = execute_tool(tool_name, arguments)
                
                logger.info(f"[Tool Result] {tool_name}: {result[:200]}..." if len(result) > 200 else f"[Tool Result] {tool_name}: {result}")
                
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            messages.extend(tool_messages)
            
            # Save to history
            if session_id:
                add_message_to_history(session_id, assistant_msg_dict)
                for tool_msg in tool_messages:
                    add_message_to_history(session_id, tool_msg)
            
            # Continue the loop to get the next response
            continue
        else:
            # No tool calls - make a streaming call for the final response
            logger.info("[stream_with_status] Making streaming call for final response")
            
            # If the non-streaming response already has content, use it
            if assistant_message.content:
                logger.info(f"[stream_with_status] Using existing content from non-streaming response: {len(assistant_message.content)} chars")
                yield {"type": "token", "content": assistant_message.content}
                
                # Save assistant message to history
                if session_id:
                    add_message_to_history(session_id, {
                        "role": "assistant",
                        "content": assistant_message.content
                    })
                
                yield {"type": "done"}
                return
            
            # No content yet - try streaming
            logger.info("[stream_with_status] No content in non-streaming response, attempting streaming call")
            
            try:
                stream = await async_client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="none",
                    stream=True,
                    extra_headers={
                        "HTTP-Referer": "https://chatiitd.devclub.in",
                        "X-OpenRouter-Title": "ChatIITD Academic Assistant",
                    }
                )
                
                full_response = ""
                async for chunk in stream:
                    # Check for cancellation during streaming
                    if cancel_event and cancel_event.is_set():
                        logger.info("[stream_with_status] Cancelled during streaming")
                        # Save partial response if any
                        if session_id and full_response:
                            add_message_to_history(session_id, {
                                "role": "assistant",
                                "content": full_response + "\n\n[Response stopped by user]"
                            })
                        yield {"type": "error", "message": "Generation stopped by user", "error_code": "cancelled"}
                        return
                    
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        yield {"type": "token", "content": content}
                
                # Save assistant message to history
                if session_id and full_response:
                    add_message_to_history(session_id, {
                        "role": "assistant",
                        "content": full_response
                    })
                
                if not full_response:
                    yield {"type": "token", "content": "I apologize, but I was unable to generate a response. Please try again."}
                
                yield {"type": "done"}
                
            except Exception as e:
                logger.error(f"[stream_with_status] Streaming failed: {e}", exc_info=True)
                yield classify_openrouter_error(e)
            
            return
    
    # Max iterations reached
    logger.warning(f"[stream_with_status] Maximum tool iterations ({MAX_TOOL_ITERATIONS}) reached")
    yield {"type": "error", "message": "Maximum processing steps reached", "error_code": "max_iterations"}


def generate_chat_title(user_message: str) -> str:
    """
    Generate a short chat title from the user's first message using the LLM.
    
    Args:
        user_message: The first message from the user
        
    Returns:
        A short title (3-6 words) for the chat, or 'New Chat' on error
    """
    logger.info(f"[generate_chat_title] Generating title for message: {user_message[:100]}...")
    
    try:
        prompt = f"""Generate a very short title (3-6 words max) for a chat that starts with this message. 
The title should summarize the main topic. Do not use quotes or special characters.
Only respond with the title, nothing else.

User message: {user_message}

Title:"""
        
        logger.info(f"[generate_chat_title] Calling OpenRouter API with model: {MODEL}")
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,  # Increased to allow for reasoning tokens + actual output
            extra_headers={
                "HTTP-Referer": "https://chatiitd.devclub.in",
                "X-OpenRouter-Title": "ChatIITD Academic Assistant",
            }
        )
        
        logger.info(f"[generate_chat_title] Raw response: {response}")
        logger.info(f"[generate_chat_title] Response choices: {response.choices}")
        
        if not response.choices:
            logger.error("[generate_chat_title] No choices in response!")
            return "New Chat"
        
        message = response.choices[0].message
        logger.info(f"[generate_chat_title] Message object: {message}")
        logger.info(f"[generate_chat_title] Message content: {message.content}")
        
        if message.content is None:
            logger.error("[generate_chat_title] Message content is None!")
            # Try to use reasoning field as fallback (some models put output there)
            if hasattr(message, 'reasoning') and message.reasoning:
                logger.info("[generate_chat_title] Using reasoning field as fallback")
                # Extract a reasonable title from the reasoning
                reasoning_text = message.reasoning.strip()
                # Try to find a title-like phrase at the end
                if len(reasoning_text) <= 100:
                    return reasoning_text
            return "New Chat"
        
        title = message.content.strip()
        
        # Ensure the title is reasonable
        if title and len(title) <= 100:
            logger.info(f"[generate_chat_title] Generated title: {title}")
            return title
        return "New Chat"
    except Exception as e:
        logger.error(f"[generate_chat_title] Failed to generate chat title: {e}", exc_info=True)
        return "New Chat"


# =====================
# CLI Interface
# =====================

def main():
    """Runs the agent in a conversational command-line loop."""
    print(f"--- IIT Delhi Academic Chatbot Initialized (Model: {MODEL}) ---")
    print("Ask me about courses or institute rules.")
    print("Type 'quit' to exit.")

    # A unique session ID for the command-line interaction
    session_id = "cli_session"
    
    while True:
        try:
            query = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
            
        if query.lower() == "quit":
            break

        response = invoke_memory_agent({
            "input": query
        }, session_id=session_id)

        print(f"Assistant: {response['output']}")
        print("\n" + "-"*50 + "\n")


logger.info(f"--- IIT Delhi Academic Chatbot Module Loaded (Model: {MODEL}) ---")


if __name__ == "__main__":
    main()
