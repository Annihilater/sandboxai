# Mentis Sandbox Experimental Features

This directory contains experimental features and integrations for the Mentis Sandbox. These features are subject to change or removal in future versions, so please use them with caution.

## Currently Supported Integrations

- [CrewAI Integration](#crewai-integration) - Integrate Mentis Sandbox with the CrewAI agent framework.
- [LangGraph Integration](#langgraph-integration) - Integrate Mentis Sandbox with the LangGraph agent framework.

## Installation

To use these experimental features, ensure you have the base `mentis-client` installed, and then install the corresponding "extras" for the integrations you need:

```bash
# Install core client and dependencies for CrewAI integration
pip install "mentis-client[crewai]"

# Install core client and dependencies for LangGraph integration (includes langchain-openai)
# Replace 'langchain-openai' with your preferred LLM provider if needed, 
# ensuring it's reflected in the package's optional dependencies.
pip install "mentis-client[langgraph]"

# Install all experimental dependencies
pip install "mentis-client[all_experimental]" 
```
*(Note: This assumes `mentis-client`'s `pyproject.toml` or `setup.py` defines these `[crewai]`, `[langgraph]`, and `[all_experimental]` extras correctly, including dependencies like `crewai`, `langgraph`, and `langchain-openai`)*


## CrewAI Integration

The CrewAI integration allows you to use the Mentis Sandbox for executing Python code and shell commands within your CrewAI Agents.

### Basic Usage

```python
import os
from mentis_client.experimental import MentisIPythonTool, MentisShellTool
from crewai import Agent, Task, Crew

# Requires OPENAI_API_KEY environment variable for the default CrewAI LLM
# os.environ["OPENAI_API_KEY"] = "YOUR_API_KEY" 

# Create Mentis tools (implicitly uses an embedded sandbox)
python_tool = MentisIPythonTool()
shell_tool = MentisShellTool()

# Create an agent that uses the Mentis tools
data_scientist = Agent(
    role="Data Scientist",
    goal="Analyze data and generate insights",
    backstory="You are an experienced data scientist skilled in data analysis and visualization.",
    tools=[python_tool, shell_tool],
    allow_delegation=False # Example: Disable delegation for simplicity
)

# Create a task
analysis_task = Task(
    description="Analyze the provided dataset '/data/input.csv' and generate summary statistics. Save the summary to '/data/summary.txt'.",
    expected_output="A text file named summary.txt containing the summary statistics.",
    agent=data_scientist
)

# Create and run the Crew
data_crew = Crew(
    agents=[data_scientist],
    tasks=[analysis_task],
    verbose=2 # Set verbosity level
)

result = data_crew.kickoff()
print("\n--- Crew Execution Result ---")
print(result)

# Remember to clean up resources if needed, although tools handle basic cleanup
python_tool.close() 
shell_tool.close() 
```

### Advanced Usage (Shared Sandbox)

You can provide an existing sandbox instance when initializing tools to share the same environment.

```python
from mentis_client import MentisSandbox
from mentis_client.experimental import MentisIPythonTool, MentisShellTool
# Import Agent, Task, Crew etc. as in the basic example

# Create a sandbox instance explicitly
# This could connect to an existing runtime or start an embedded one
sandbox = MentisSandbox.create() 

try:
    # Create tools using the existing sandbox
    python_tool = MentisIPythonTool(sandbox=sandbox)
    shell_tool = MentisShellTool(sandbox=sandbox)

    # --- Define Agent, Task, Crew as in Basic Usage ---
    data_scientist = Agent(
        role="Shared Sandbox Data Scientist",
        goal="Perform analysis in a persistent sandbox",
        backstory="You operate within a shared, persistent sandbox environment.",
        tools=[python_tool, shell_tool]
    )
    analysis_task = Task(
        description="Load data from '/shared/data.pkl', perform calculations, save results to '/shared/results.pkl'.",
        expected_output="A pickle file named results.pkl in the /shared directory.",
        agent=data_scientist
    )
    data_crew = Crew(
        agents=[data_scientist],
        tasks=[analysis_task],
        verbose=2
    )
    
    result = data_crew.kickoff()
    print("\n--- Shared Sandbox Crew Execution Result ---")
    print(result)

finally:
    # Explicitly delete the sandbox when done if you created it explicitly
    if sandbox:
        print("Deleting shared sandbox...")
        sandbox.delete()
        print("Sandbox deleted.")

```

## LangGraph Integration

The LangGraph integration allows you to use the Mentis Sandbox for Python code execution within your LangGraph workflows, typically invoked via LangGraph's standard tool handling mechanisms.

*(Note: A `LangGraphMentisShellTool` might also exist; adapt examples if needed.)*

### Simplest Usage (Tool Trigger Test)

This example demonstrates the most basic way to trigger the tool directly within a graph, without involving an LLM, purely for testing the tool invocation mechanism.

```python
import logging
import os
from typing import TypedDict, Annotated

# Configure logging (set to DEBUG to see sandbox details)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
logger = logging.getLogger("mentis-minimal-tool-test-en")

try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages 
    from langgraph.prebuilt import ToolNode # Use standard ToolNode
    from langchain_core.messages import BaseMessage, AIMessage, ToolMessage 
    from mentis_client.experimental import MentisPythonTool
except ImportError as e:
    logger.error(f"Required libraries not found: {e}. Please install: pip install 'mentis-client[langgraph]'")
    exit(1)

# --- Define State ---
class SimpleToolTestState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# --- Initialize Tool and ToolNode ---
logger.info("Initializing MentisPythonTool...")
mentis_tool = None
try:
    mentis_tool = MentisPythonTool(sync_timeout=60.0) 
    tool_name = mentis_tool.name
    tools = [mentis_tool]
    tool_node = ToolNode(tools=tools) # Use standard ToolNode
    logger.info(f"MentisPythonTool ('{tool_name}') and ToolNode initialized successfully.")
except Exception as e:
    logger.exception("FATAL: Failed to initialize Mentis tool or ToolNode. Exiting.")
    raise RuntimeError("Halting script due to tool initialization failure.") from e 

# --- Define Node to Generate Tool Call ---
def generate_tool_call_node(state: SimpleToolTestState):
    """Directly generates an AIMessage to trigger the Mentis tool."""
    logger.info("--- Node: generate_tool_call ---")
    code_to_run = "import platform; print(f'Hello from Mentis Sandbox on {platform.system()}!'); result = 42 + 100; print(f'Calculation result: {result}'); result"
    tool_call_id = "minimal_test_call_en_001"
    logger.info(f"Hardcoding tool call for '{tool_name}' with ID '{tool_call_id}'")
    ai_message = AIMessage(
        content="Simulating request: Please run this Python code.",
        tool_calls=[{"id": tool_call_id, "name": tool_name, "args": {"code": code_to_run}}]
    )
    return {"messages": [ai_message]}

# --- Build the Graph ---
logger.info("Building the simplified graph...")
graph_builder = StateGraph(SimpleToolTestState)
graph_builder.add_node("call_generator", generate_tool_call_node)
graph_builder.add_node("tool_runner", tool_node) 
graph_builder.set_entry_point("call_generator")
graph_builder.add_edge("call_generator", "tool_runner")
graph_builder.add_edge("tool_runner", END) # End after tool runs

# --- Compile and Run ---
try:
    graph = graph_builder.compile()
    logger.info("Graph compiled successfully.")
    
    logger.info("--- Starting Minimal Tool Test Execution ---")
    final_state = None
    for state_update in graph.stream({"messages": []}, stream_mode="values"):
        final_state = state_update
        # Optional: print step outputs
        # ... (add printing logic if desired) ...

    logger.info("--- Minimal Tool Test Execution Finished ---")
    # Check final_state['messages'] to verify ToolMessage content
    print("Final State Messages:")
    # ... (add final state printing logic) ...
    # Verify ToolMessage content for success/error

except Exception as e:
    logger.exception("An error occurred during graph execution.")
finally:
    if mentis_tool and hasattr(mentis_tool, 'close'):
        logger.info("Cleaning up MentisPythonTool resources...")
        mentis_tool.close() 
        logger.info("Cleanup complete.")
    logger.info("Minimal tool test script finished.")

```

### Basic Usage (Agent Loop with LLM)

This example shows a more typical pattern where an LLM decides when to call the Mentis tool and processes its result within a stateful graph.

```python
import logging
import os
from typing import TypedDict, Annotated, Sequence

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
logger = logging.getLogger("mentis-langgraph-agent-en")

# Requires OPENAI_API_KEY environment variable
# os.environ["OPENAI_API_KEY"] = "YOUR_API_KEY" 

try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages 
    from langgraph.prebuilt import ToolNode # Use standard ToolNode
    from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
    from langchain_openai import ChatOpenAI # Needs langchain-openai installed
    from mentis_client.experimental import MentisPythonTool
except ImportError as e:
    logger.error(f"Required libraries not found: {e}. Please install: pip install 'mentis-client[langgraph]'")
    exit(1)

# --- Define State ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# --- Initialize LLM, Tool, and ToolNode ---
logger.info("Initializing LLM and Tool...")
mentis_tool = None
try:
    llm = ChatOpenAI(model="gpt-4o") # Or your preferred model
    mentis_tool = MentisPythonTool(sync_timeout=120.0) 
    tools = [mentis_tool]
    # Bind tool to LLM for function calling
    llm_with_tools = llm.bind_tools(tools) 
    tool_node = ToolNode(tools=tools) # Use standard ToolNode
    logger.info(f"LLM, MentisPythonTool ('{mentis_tool.name}'), and ToolNode initialized.")
except Exception as e:
    logger.exception("FATAL: Failed to initialize components.")
    if mentis_tool and hasattr(mentis_tool, 'close'):
        mentis_tool.close()
    raise RuntimeError("Halting script due to component initialization failure.") from e

# --- Define Agent Node ---
def agent_node(state: AgentState):
    """Invokes the LLM to decide the next action or process tool results."""
    logger.info("Agent Node executing...")
    messages = state['messages']
    last_message = messages[-1] if messages else None

    # Prevent loop if LLM tries to call tool immediately after tool result
    if isinstance(last_message, ToolMessage):
        logger.info("Last message was ToolMessage. Calling LLM for final response.")
        response = llm_with_tools.invoke(messages) 
        if getattr(response, 'tool_calls', None):
            logger.warning("LLM tried tool call after ToolMessage! Overriding.")
            return {"messages": [AIMessage(content="Tool executed. Processing finished.")]}
        return {"messages": [response]}
    else: # Human message or other state
        logger.info("Calling LLM for next step...")
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

# --- Define Router ---
def should_continue(state: AgentState) -> str:
    """Routes to tools if the LLM requested them, otherwise ends."""
    last_message = state['messages'][-1] if state['messages'] else None
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        logger.info("Router: Tool call detected, routing to 'tools'.")
        return "tools"
    else:
        logger.info("Router: No tool call, routing to END.")
        return END

# --- Build Graph ---
logger.info("Building the agent graph...")
graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", tool_node)
graph_builder.set_entry_point("agent")
graph_builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph_builder.add_edge("tools", "agent") # Always go back to agent after tools run

# --- Compile and Run ---
try:
    graph = graph_builder.compile()
    logger.info("Graph compiled successfully.")
    
    logger.info("--- Starting Agent Execution ---")
    initial_input = {"messages": [HumanMessage(content="Calculate 12 * (sqrt(144) + 3) using Python.")]}
    for event in graph.stream(initial_input, stream_mode="values"):
        # Print or process events as needed
        print(f"--- State Update ---")
        print(event) 

    logger.info("--- Agent Execution Finished ---")

except Exception as e:
    logger.exception("An error occurred during graph execution.")
finally:
    if mentis_tool and hasattr(mentis_tool, 'close'):
        logger.info("Cleaning up MentisPythonTool resources...")
        mentis_tool.close() 
        logger.info("Cleanup complete.")
    logger.info("Agent script finished.")

```

### Advanced Usage (Custom Tool Configuration)

You can customize the tool's behavior by providing configuration objects during initialization.

```python
from mentis_client.experimental import MentisPythonTool, MentisPythonToolConfig # Assuming config classes exist

# Define custom configuration for the Python tool
python_config = MentisPythonToolConfig(
    name="python_data_processor",
    description="Executes Python code for data processing tasks in a secure sandbox.",
    sync_timeout=180,  # Set a longer timeout (in seconds)
    # Add other relevant config options here, e.g., startup_script, work_dir
)

# Create the tool instance with the custom configuration
# Note: This configured tool would then be used when building the graph 
# in the "Basic Usage (Agent Loop with LLM)" example above.
custom_python_tool = MentisPythonTool(config=python_config)

# You can now use 'custom_python_tool' in the 'tools' list passed to 
# llm.bind_tools() and ToolNode(...) in the graph setup.
print(f"Custom tool created: Name='{custom_python_tool.name}', Timeout='{custom_python_tool.sync_timeout}'") 
# Add cleanup for this tool instance if used separately
# custom_python_tool.close() 
```

## Important Notes

- These features are experimental and their API or behavior may change or be removed in future releases without prior notice.
- Ensure you have installed the necessary dependencies for the integrations you plan to use (see Installation section). Required libraries like `langchain-openai` for LLM examples must also be installed.
- API keys (e.g., `OPENAI_API_KEY`) may be required for examples involving Large Language Models and should be set as environment variables.
- Sandbox resources are typically cleaned up automatically when the corresponding tool or sandbox object is garbage collected. However, to ensure timely and reliable cleanup, especially in long-running applications or after errors, it is **strongly recommended** to explicitly call the tool's `.close()` method (or the sandbox's `.delete()` method if created separately) using a `try...finally` block or a context manager (`with MentisPythonTool(...) as tool:`) if available.

## Contributing

Contributions to Mentis Sandbox experimental features are welcome! If you have suggestions or encounter issues, please feel free to submit an issue or pull request on the project repository.