import streamlit as st
import pandas as pd
import json
from pathlib import Path
from openai import OpenAI
import os
import tempfile
from PyPDF2 import PdfReader
import io
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

st.set_page_config(page_title="Prompt Playground", layout="wide")

# Initialize session state variables
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'system_prompt' not in st.session_state:
    st.session_state.system_prompt = ""
if 'assistant_id' not in st.session_state:
    st.session_state.assistant_id = None
if 'thread_id' not in st.session_state:
    st.session_state.thread_id = None
if 'client' not in st.session_state:
    st.session_state.client = None
if 'selected_model' not in st.session_state:
    st.session_state.selected_model = 'gpt-4o'

# Initialize OpenAI client with API key from environment variable
if not st.session_state.client:
    api_key = os.getenv('OPENAI_API_KEY')
    if api_key:
        st.session_state.client = OpenAI(api_key=api_key)

def read_pdf_content(file):
    """Read content from PDF file"""
    try:
        pdf_reader = PdfReader(io.BytesIO(file.getvalue()))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def read_file_content(uploaded_file):
    """Read content from uploaded file based on file type"""
    if uploaded_file is None:
        return ""
    
    file_extension = Path(uploaded_file.name).suffix.lower()
    
    try:
        if file_extension == '.pdf':
            content = read_pdf_content(uploaded_file)
        elif file_extension == '.txt':
            content = uploaded_file.getvalue().decode('utf-8')
        elif file_extension == '.csv':
            df = pd.read_csv(uploaded_file)
            content = df.to_string()
        elif file_extension == '.json':
            content = json.load(uploaded_file)
            content = json.dumps(content, indent=2)
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(uploaded_file)
            content = df.to_string()
        else:
            content = "Unsupported file type"
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def initialize_assistant(client, instructions):
    """Initialize or update the OpenAI assistant"""
    try:
        # Create a new assistant
        assistant = client.beta.assistants.create(
            name="File Analysis Assistant",
            instructions=instructions,
            tools=[{"type": "code_interpreter"}],
            model=st.session_state.selected_model
        )
        return assistant.id
    except Exception as e:
        st.error(f"Error creating assistant: {str(e)}")
        return None

def get_ai_response(client, thread_id, prompt):
    """Get response using the Assistants API"""
    try:
        # Add the message to the thread
        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt
        )

        # Run the assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=st.session_state.assistant_id
        )

        # Wait for the run to complete
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                return "Error: Assistant run failed"
            time.sleep(1)

        # Get the latest message from the thread
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        return messages.data[0].content[0].text.value

    except Exception as e:
        return f"Error: {str(e)}"

# Sidebar for configuration
with st.sidebar:
    st.title("Configuration")
    
    if not st.session_state.client:
        st.error("OpenAI API key not found in environment variables. Please set OPENAI_API_KEY.")
    
    # Model selection
    model_options = ['gpt-4o', 'gpt-4o-mini', 'o1-preview','o1-mini']
    selected_model = st.selectbox(
        "Select Model",
        options=model_options,
        index=model_options.index(st.session_state.selected_model)
    )
    
    # Update model if changed
    if selected_model != st.session_state.selected_model:
        st.session_state.selected_model = selected_model
        if st.session_state.client:
            # Reinitialize assistant with new model
            assistant_id = initialize_assistant(st.session_state.client, st.session_state.system_prompt)
            if assistant_id:
                st.session_state.assistant_id = assistant_id
                thread = st.session_state.client.beta.threads.create()
                st.session_state.thread_id = thread.id
                st.session_state.messages = []
                st.rerun()
    
    # System prompt input
    st.subheader("System Prompt")
    system_prompt_input = st.text_area(
        "Enter base system prompt",
        value=st.session_state.system_prompt,
        height=150
    )
    
    # File upload
    st.subheader("Upload Files")
    uploaded_files = st.file_uploader(
        "Upload files to include in context",
        accept_multiple_files=True,
        type=['txt', 'csv', 'json', 'xlsx', 'xls', 'pdf']
    )
    
    # Read and combine file contents
    file_contents = ""
    if uploaded_files:
        for file in uploaded_files:
            content = read_file_content(file)
            file_contents += f"\n### Content from {file.name}:\n{content}\n"

    # Update system prompt
    if system_prompt_input or file_contents:
        st.session_state.system_prompt = f"{system_prompt_input}\n\nContext from uploaded files:\n\n{file_contents}"
        
        # Initialize or update assistant if we have a client
        if st.session_state.client:
            # Initialize assistant with combined prompt
            assistant_id = initialize_assistant(st.session_state.client, st.session_state.system_prompt)
            if assistant_id:
                st.session_state.assistant_id = assistant_id
                # Create a new thread if we don't have one
                if not st.session_state.thread_id:
                    thread = st.session_state.client.beta.threads.create()
                    st.session_state.thread_id = thread.id

# Main chat interface
st.title("Prompt Playground")

# Display current system prompt
with st.expander("Current System Prompt", expanded=False):
    st.code(st.session_state.system_prompt)

# Chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# Chat input
if prompt := st.chat_input("Enter your message"):
    if not st.session_state.client:
        st.error("OpenAI API key not found in environment variables. Please set OPENAI_API_KEY.")
        st.stop()
    
    if not st.session_state.assistant_id or not st.session_state.thread_id:
        st.error("Please set up the system prompt and wait for assistant initialization.")
        st.stop()
    
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    
    # Get and display assistant response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = get_ai_response(
                st.session_state.client,
                st.session_state.thread_id,
                prompt
            )
            st.write(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

# Clear chat button
if st.button("Clear Chat"):
    if st.session_state.client and st.session_state.thread_id:
        # Create a new thread
        thread = st.session_state.client.beta.threads.create()
        st.session_state.thread_id = thread.id
    st.session_state.messages = []
    st.rerun()
