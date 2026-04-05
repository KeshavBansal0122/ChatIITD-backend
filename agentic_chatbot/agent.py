"""
IIT Delhi Academic Chatbot Agent using OpenRouter.

This module provides the agent functionality for the chatbot using OpenRouter's API
with the OpenAI SDK. It implements a ReAct-style agent with tool calling capabilities.
"""

import os
import json
import sqlite3
import logging
from typing import AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv

from .tools import TOOLS, TOOL_MAPPING, execute_tool


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Load environment variables from a .env file
load_dotenv('../.env')
load_dotenv('.env')


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
with open('agentic_chatbot/system_prompt.txt', 'r') as file:
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
        
        if user_info_parts:
            user_context_section = "\n\n---\n\n## **User Context**\n\nYou are currently assisting the following user:\n" + "\n".join(f"- {part}" for part in user_info_parts)
            prompt += user_context_section
    
    return prompt


# =====================
# Chat History Management (SQLite)
# =====================

def get_db_connection():
    """Get a connection to the messages database."""
    return sqlite3.connect('messages.db')


def init_message_history_db():
    """Initialize the message history database if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# Initialize the database on module load
init_message_history_db()


def get_chat_history(session_id: str) -> list[dict]:
    """Retrieve chat history for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT role, content, tool_calls, tool_call_id, name
        FROM message_history
        WHERE session_id = ?
        ORDER BY created_at ASC
    ''', (session_id,))
    
    messages = []
    for row in cursor.fetchall():
        role, content, tool_calls, tool_call_id, name = row
        message = {"role": role}
        
        if content is not None:
            message["content"] = content
        
        if tool_calls:
            message["tool_calls"] = json.loads(tool_calls)
            # For assistant messages with tool_calls, content should be null or omitted
            if role == "assistant" and not content:
                message["content"] = None
        
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        
        if name:
            message["name"] = name
            
        messages.append(message)
    
    conn.close()
    return messages


def add_message_to_history(session_id: str, message: dict):
    """Add a message to the chat history."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
    
    cursor.execute('''
        INSERT INTO message_history (session_id, role, content, tool_calls, tool_call_id, name)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        session_id,
        message.get("role"),
        message.get("content"),
        tool_calls_json,
        message.get("tool_call_id"),
        message.get("name")
    ))
    
    conn.commit()
    conn.close()


def clear_chat_history(session_id: str):
    """Clear chat history for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM message_history WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()


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
    print('AGENT INVOKED, USER CONTEXT', user_context)
    user_message = input_dict.get("input", "")
    logger.info(f"[invoke_memory_agent] Starting for message: {user_message[:100]}...")
    logger.info(f"[invoke_memory_agent] Session ID: {session_id}")
    
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
            # No tool calls, we have the final response
            logger.info("[stream_memory_agent] No tool calls, returning final response")
            
            # Get content from the response, fall back to reasoning if content is None
            # Some models (like z-ai/glm-4.5-air:free) put output in reasoning instead of content
            final_content = assistant_message.content
            if final_content is None and hasattr(assistant_message, 'reasoning') and assistant_message.reasoning:
                logger.info("[stream_memory_agent] Content is None, using reasoning field as fallback")
                final_content = assistant_message.reasoning
            
            if final_content:
                logger.info(f"[stream_memory_agent] Yielding response of length: {len(final_content)}")
                # Save assistant message to history
                if session_id:
                    add_message_to_history(session_id, {
                        "role": "assistant",
                        "content": final_content
                    })
                yield final_content
            else:
                logger.warning("[stream_memory_agent] No content in response, making a new streaming call")
                # Only make a new streaming call if we truly have no content
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
