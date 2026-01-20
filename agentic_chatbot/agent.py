import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.vectorstores import Qdrant
import qdrant_client
from langchain.tools.retriever import create_retriever_tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv
from qdrant_client.http.models import ScoredPoint
from langchain_core.documents import Document
import json
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from agentic_chatbot.tools import get_rules_section_tool, get_course_data_tool, get_programme_structure_tool, query_sqlite_db_tool

# LangGraph Imports
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from typing import Annotated, TypedDict
from typing_extensions import TypedDict


# Load environment variables from a .env file
load_dotenv('../.env')
load_dotenv('.env')

class QdrantWithObjectPayload(Qdrant):
    """
    Custom Qdrant vector store class that handles object payloads.
    It serializes the 'page_content' into a JSON string if it is a dictionary.
    """
    def _document_from_scored_point(
        self,
        scored_point: ScoredPoint,
        collection_name,
        content_payload_key: str,
        metadata_payload_key: str,
    ) -> Document:
        """Overrides the base method to handle object-like payloads."""
        payload = scored_point.payload or {}
        page_content = payload.get(content_payload_key)
        
        # If the content is a dictionary (i.e., a JSON object), serialize it
        if isinstance(page_content, dict):
            # Using indent for better readability for the LLM
            page_content = json.dumps(page_content, indent=2)
        
        metadata = payload.get(metadata_payload_key) or {}
        
        # Add score and id to metadata, similar to the base class implementation
        metadata["_score"] = scored_point.score
        metadata["_id"] = scored_point.id

        return Document(
            page_content=page_content or "", # Ensure page_content is not None
            metadata=metadata,
        )


# --- 0. Setup ---
# Set up the necessary API keys. You will only need a Google API Key for Gemini.
# os.environ["GOOGLE_API_KEY"] = "YOUR_GOOGLE_API_KEY"

# Initialize the LLM and Embeddings model
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


# --- 1. Connect to Existing Qdrant RAG Data Sources ---

# Initialize the Qdrant client to connect to your local instance.
# Use environment variable for Docker compatibility, default to localhost for local dev
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
client = qdrant_client.QdrantClient(url=QDRANT_URL)

# Connect to the existing 'rules' collection
rules_vector_store = QdrantWithObjectPayload(
    client=client,
    collection_name="rules",
    embeddings=embeddings,
    content_payload_key='content',
    metadata_payload_key='metadata'
)
rules_retriever = rules_vector_store.as_retriever()

# Connect to the existing 'courses' collection
courses_vector_store = QdrantWithObjectPayload(
    client=client,
    collection_name="courses",
    embeddings=embeddings,
    content_payload_key='description',
    metadata_payload_key='metadata'
)
courses_retriever = courses_vector_store.as_retriever()

# --- 2. Add a Free, Self-Run Reranking Step ---

# Initialize a free, self-run cross-encoder model from HuggingFace.
# The first time you run this, it will download the model weights (~227MB).
# This model runs locally on your machine (CPU or GPU if available).
model = HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-base")

# The compressor uses the cross-encoder model to rerank documents.
# It returns the top 3 most relevant documents.
compressor = CrossEncoderReranker(model=model, top_n=3)

# Create compression retrievers that will use the local reranker.
rules_compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor, base_retriever=rules_retriever
)
courses_compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor, base_retriever=courses_retriever
)


# --- 3. Define Tools with Refined Descriptions ---

# The descriptions are crucial. They guide the agent on when to use each tool.
# We will now use the compression retrievers in our tools.

rules_tool = create_retriever_tool(
    rules_compression_retriever,
    "search_iitd_rules",
    """
    Use this tool to semantically search for certain queries about IIT Delhi's rules for undergraduate or postgraduate students.
    Use this tool when you cannot determine the section of rules to look up, or when the user query is more general.
    """,
)

courses_tool = create_retriever_tool(
    courses_compression_retriever,
    "search_iitd_courses",
    """
    Use this tool to find information about specific courses offered at IIT Delhi, but you want to search by topic or keywords rather than course code.
    If the course code is known, use the get_course_data_tool instead.
    """,
)

tools = [rules_tool, courses_tool, get_rules_section_tool, get_course_data_tool, get_programme_structure_tool, query_sqlite_db_tool]


# --- 4. Create the Conversational Agent (LangGraph) ---

# Define the state of the graph
class State(TypedDict):
    messages: Annotated[list, add_messages]

# Define the LLM with tools bound
llm_with_tools = llm.bind_tools(tools)

# Define the node that calls the model
def call_model(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

# Initialize the graph
workflow = StateGraph(State)

# Add nodes
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

# Add edges
workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent",
    tools_condition,
)
workflow.add_edge("tools", "agent")

# Initialize memory for the graph
memory = MemorySaver()

# Compile the graph
agent_executor = workflow.compile(checkpointer=memory)

# Load System Prompt
with open('agentic_chatbot/system_prompt.txt', 'r') as file:
    system_prompt_content = file.read()
system_message = SystemMessage(content=system_prompt_content)

def invoke_memory_agent(input_dict, session_id=None):
    """
    Invokes the LangGraph agent.
    Adapts the input format {"input": "..."} to {"messages": [...]}.
    """
    user_input = input_dict.get("input")
    config = {"configurable": {"thread_id": session_id or "default"}}
    
    # We need to prepend the system prompt if it's a new conversation, 
    # but LangGraph handles history via checkpointer. 
    # For simplicity, we pass the user message. 
    # To ensure system prompt is always present, we can check state or just rely on the LLM 
    # (or prepend it every time if it's a chat model, but simpler to add to graph state initialization if needed).
    # Here we'll just prepend it to the current input messages if it's the first turn, 
    # but since we don't easily know if it's the first turn without checking history, 
    # we can try to optimize. 
    # BETTER APPROACH: Just send user message. The system prompt should be part of the `messages` list
    # or we can modify `call_model` to prepend it. 
    # Let's modify `call_model` slightly to ensure system prompt is there? 
    # No, let's just prepend it to the input messages list if we want to be safe, 
    # but `add_messages` merges.
    # We will pass the system message in the input if it's critical, 
    # but for now let's just pass user input.
    
    # To properly support system prompt:
    input_messages = [HumanMessage(content=user_input)]
    
    # Fetch current state to see if history exists? 
    # We can just trust the checkpointer. 
    # But we need the system prompt to be "active".
    # One way: Always include SystemMessage at the start? 
    
    # Let's modify `call_model` to prepend system prompt if not present?
    # Or simpler: Just define `call_model` to use a prompt template.
    
    # Let's stick to simple: Pass System Message + User Message.
    # If history exists, `add_messages` will append.
    # If we send SystemMessage every time, it might duplicate.
    # We should only send it if it's a fresh thread.
    
    snapshot = agent_executor.get_state(config)
    messages_payload = []
    if not snapshot.values: # Empty history
        messages_payload.append(system_message)
    
    messages_payload.append(HumanMessage(content=user_input))
    
    # Run the graph
    # stream_mode="values" returns the full state at each step. 
    # We want final output.
    final_state = agent_executor.invoke(
        {"messages": messages_payload},
        config=config
    )
    
    # Extract the last message content
    last_message = final_state["messages"][-1]
    return {"output": last_message.content}

print("--- IIT Delhi Academic Chatbot Initialized (Model: Gemini Flash, Reranker: BAAI/bge-reranker-base) ---")
print("Ask me about courses or institute rules.")
print("Type 'quit' to exit.")

# Initialize chat history
chat_history = []


def main():
    """Runs the agent in a conversational command-line loop."""
    print("--- IIT Delhi Academic Chatbot Initialized (Model: Gemini Flash, Reranker: BAAI/bge-reranker-base) ---")
    print("Ask me about courses or institute rules.")
    print("Type 'quit' to exit.")

    # A unique session ID for the command-line interaction
    session_id = "cli_session"
    
    # --- 5. Run the Agent in a Conversational Loop ---
    while True:
        query = input("You: ")
        if query.lower() == "quit":
            break

        # The agent now takes both the input and a session_id
        response = invoke_memory_agent({
            "input": query
        }, session_id=session_id)

        print(f"Assistant: {response['output']}")
        print("\n" + "-"*50 + "\n")

if __name__ == "__main__":
    main()