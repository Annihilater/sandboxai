# filepath: /Users/peng/Dev/AI_CODING/sandboxai/python/examples/langgraph_minimal_tool_test.py
import logging
import os
from typing import TypedDict, Annotated

# --- Configure Logging ---
# Set to DEBUG to see detailed sandbox logs if needed
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-minimal-tool-test")

# --- Attempt Imports ---
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages # Use add_messages for state
    from langgraph.prebuilt import ToolNode
    from langchain_core.messages import BaseMessage, AIMessage, ToolMessage 
except ImportError as e:
    logger.error(f"Required libraries not found: {e}. Please install: pip install langgraph langchain-core")
    exit(1)

# Import Mentis client components
try:
    from mentis_client.experimental.langgraph import MentisPythonTool
except ImportError as e:
    logger.error(f"Mentis client library not found or setup incorrectly: {e}. Please install it.")
    exit(1)

# --- Define Minimal State ---
class SimpleToolTestState(TypedDict):
    # Only need messages to pass tool calls and results
    messages: Annotated[list[BaseMessage], add_messages]

# --- Initialize Tool and ToolNode ---
logger.info("Initializing MentisPythonTool...")
mentis_tool = None
try:
    mentis_tool = MentisPythonTool(sync_timeout=60.0) 
    tool_name = mentis_tool.name 
    # Log success *before* potential failure below? Or maybe move inside ToolNode init...
    # Let's log after ToolNode is also okay

    tools = [mentis_tool]
    tool_node = ToolNode(tools=tools) 
    logger.info(f"MentisPythonTool ('{tool_name}') and ToolNode initialized successfully.") # Consolidated log

except Exception as e:
    logger.exception("FATAL: Failed to initialize Mentis tool or ToolNode. Exiting.")
    # ADD OR MODIFY THIS LINE to ensure the script stops:
    raise RuntimeError("Halting script due to tool initialization failure.") from e

# --- Define Node to Generate Tool Call ---
def generate_tool_call_node(state: SimpleToolTestState):
    """Directly generates an AIMessage to trigger the Mentis tool."""
    logger.info("--- Node: generate_tool_call ---")
    
    code_to_run = "import platform; print(f'Hello from Mentis Sandbox on {platform.system()}!'); result = 42 + 100; print(f'Calculation result: {result}'); result"
    tool_call_id = "minimal_test_call_001" # Simple hardcoded ID
    
    logger.info(f"Hardcoding tool call for '{tool_name}' with ID '{tool_call_id}'")
    
    # Create the AIMessage structure that ToolNode expects
    ai_message = AIMessage(
        content="Simulating request: Please run this Python code.",
        tool_calls=[
            {
                "id": tool_call_id,
                "name": tool_name, # Use the actual tool name obtained during init
                "args": {"code": code_to_run} # Arguments expected by MentisPythonTool
            }
        ]
    )
    
    # Return the message to be added to the state
    return {"messages": [ai_message]}

# --- Build the Graph ---
logger.info("Building the simplified graph...")
graph_builder = StateGraph(SimpleToolTestState)

# Add the nodes
graph_builder.add_node("call_generator", generate_tool_call_node)
graph_builder.add_node("tool_runner", tool_node) # The prebuilt ToolNode

# Set the entry point
graph_builder.set_entry_point("call_generator")

# Define the simple flow: generator -> tool_runner -> END
graph_builder.add_edge("call_generator", "tool_runner")
graph_builder.add_edge("tool_runner", END) # End immediately after the tool runs

# --- Compile the Graph ---
try:
    graph = graph_builder.compile()
    logger.info("Graph compiled successfully.")
except Exception as e:
    logger.exception("Failed to compile graph.")
    # Attempt cleanup even if compile fails, though tool might be None
    if mentis_tool and hasattr(mentis_tool, 'close'):
        mentis_tool.close()
    raise e

# --- Run the Graph ---
if __name__ == "__main__":
    logger.info("--- Starting Minimal Tool Test Execution ---")
    
    # Initial state can be empty messages
    initial_input = {"messages": []} 
    final_state = None
    
    try:
        # Use invoke for a single run, or stream to see steps
        # final_state = graph.invoke(initial_input) 
        
        print("\nStreaming graph execution step-by-step:")
        for state_update in graph.stream(initial_input, stream_mode="values"):
             final_state = state_update # Capture the latest state
             step_messages = final_state.get('messages', [])
             if step_messages:
                 last_msg = step_messages[-1]
                 print(f"\n--- State Update ---")
                 print(f"Last Message Type: {type(last_msg).__name__}")
                 print(f"Content: {getattr(last_msg, 'content', '[N/A]')}")
                 if isinstance(last_msg, AIMessage) and getattr(last_msg, 'tool_calls', None):
                     print(f"Tool Calls: {last_msg.tool_calls}")
                 if isinstance(last_msg, ToolMessage):
                     print(f"Tool Call ID: {getattr(last_msg, 'tool_call_id', 'N/A')}")
                     print(f"Tool Result (Content): {last_msg.content}") # This shows success/failure
             else:
                 print("\n--- State Update (no messages) ---")
                 print(f"{final_state}")


        print("\n--- Minimal Tool Test Execution Finished ---")
        print("Final State Messages:")
        if final_state and final_state.get('messages'):
             for i, msg in enumerate(final_state['messages']):
                 content = getattr(msg, 'content', '[No Content]')
                 print(f"- {i+1}. {type(msg).__name__}: {content}")
                 if isinstance(msg, AIMessage) and getattr(msg, 'tool_calls', None):
                     print(f"  Tool Calls: {msg.tool_calls}")
                 if isinstance(msg, ToolMessage):
                     print(f"  Tool Call ID: {getattr(msg, 'tool_call_id', 'N/A')}")
        else:
             print("No final state messages found or final state is empty.")
             
        # Check the final ToolMessage for success indication
        if final_state and final_state.get('messages'):
            last_message = final_state['messages'][-1]
            if isinstance(last_message, ToolMessage):
                 print("\nSUCCESS: Tool execution completed and returned a ToolMessage.")
            else:
                 print("\nNOTE: Graph finished, but the last message wasn't a ToolMessage. Check logs.")
        else:
             print("\nWARNING: Could not verify final state or ToolMessage.")


    except Exception as e:
        # This will catch errors during graph execution itself
        logger.exception("An error occurred during graph execution.")
        print(f"\nERROR during execution: {e}")
    finally:
        # Ensure cleanup happens
        if mentis_tool and hasattr(mentis_tool, 'close'):
            try:
                logger.info("Cleaning up MentisPythonTool resources...")
                mentis_tool.close() 
                logger.info("Cleanup complete.")
            except Exception as cleanup_error:
                logger.error(f"Error during tool cleanup: {cleanup_error}")
        
        logger.info("Minimal tool test script finished.")