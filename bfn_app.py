import streamlit as st
from snowflake.cortex import Complete
from snowflake.core import Root
import pandas as pd
import json

NUM_CHUNKS = 3
SLIDE_WINDOW = 5
CORTEX_SEARCH_DATABASE = "BFN_PROJECT"
CORTEX_SEARCH_SCHEMA = "DATA"
CORTEX_SEARCH_SERVICE = "CC_SEARCH_SERVICE_CS"

# Columns to query in the search service
COLUMNS = [
    "chunk",
    "relative_path",
    "linked_url",
    "category"
]

# Establish Snowflake connection
cnx = st.connection('snowflake')
session = cnx.session()
root = Root(session)
svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]
   
### Functions
     
def config_options():
    st.sidebar.selectbox('Select your model:',(
                                    'reka-flash',
                                    'mixtral-8x7b',
                                    'snowflake-arctic',
                                    'mistral-large',
                                    'llama3-8b',
                                    'llama3-70b',
                                     'mistral-7b',
                                     'llama2-70b-chat',
                                     'gemma-7b'), key="model_name")
    # Creating category selectbox
    categories = session.table('docs_chunks_table').select('category').distinct().collect()
    cat_list = ['ALL']
    for cat in categories:
        cat_list.append(cat.CATEGORY)
    st.sidebar.selectbox('Select what products you are looking for', cat_list, key = "category_value")

    # Session state for debugging purposes
    st.sidebar.expander("Session State").write(st.session_state)   
    
def init_messages():
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
def get_similar_chunks_search_service(query):
    if st.session_state.category_value == "ALL":
        response = svc.search(query, COLUMNS, limit=NUM_CHUNKS)
    else: 
        filter_obj = {"@eq": {"category": st.session_state.category_value} }
        response = svc.search(query, COLUMNS, filter=filter_obj, limit=NUM_CHUNKS)

    st.sidebar.json(response.json())
    return response.json()  

def get_chat_history():
    chat_history = []
    start_index = max(0, len(st.session_state.messages) - SLIDE_WINDOW)
    for i in range(start_index, len(st.session_state.messages) - 1):
        chat_history.append(st.session_state.messages[i])
    return chat_history
    
def summarize_question_with_history(chat_history, question):
    # To get the right context, use the LLM to first summarize the previous conversation
    # This will be used to get embeddings and find similar chunks in the docs for context
    prompt = f"""
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natural language. 
        Answer with only the query. Do not add any explanation.
        
        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        """
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    summary = df_response[0].RESPONSE

    st.sidebar.text("Summary to be used to find similar chunks in the docs:")
    st.sidebar.caption(summary)

    return summary.replace("'", "")

def create_prompt(myquestion):
    chat_history = get_chat_history()
    if chat_history:  # There is chat_history, so not first question
        question_summary = summarize_question_with_history(chat_history, myquestion)
        prompt_context = get_similar_chunks_search_service(question_summary)
    else:
        prompt_context = get_similar_chunks_search_service(myquestion)  # First question when using history
  
    prompt = f"""
           You are an expert chat assistant that extracts information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags.
           When answering the question contained between <question> and </question> tags,
           be concise and do not hallucinate. 
           If you don’t have the information just say so.
           
           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your answer.

           Only answer the question if you can extract it from the CONTEXT provided.
           
           <chat_history>
           {chat_history}
           </chat_history>
           <context>          
           {prompt_context}
           </context>
           <question>  
           {myquestion}
           </question>
           Answer: 
           """
    
    json_data = json.loads(prompt_context)
    linked_url = set(item['linked_url'] for item in json_data['results'])
    return prompt, linked_url

def answer_question(myquestion):
    prompt, linked_url = create_prompt(myquestion)
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    response = df_response[0].RESPONSE
    return response, linked_url

def main():
    css = """
    <style>
    .seledin-title {
        color: #32CD32;  /* Seledin color (LimeGreen in CSS color names) */
    }
    </style>
    """
    # Inject the CSS into the app
    st.markdown(css, unsafe_allow_html=True)

    # Use st.markdown to display the title with the custom class
    st.title(f":speech_balloon: Breastfeeding Network Drug in Breastmilk Factsheets' Assistant")
    st.write('''<p style="color:purple;">The information provided is taken from various reference sources. It is provided as a guideline.
             No responsibility can be taken by the author or BfN for the way in which the information is used. 
             Clinical decisions remain the responsibility of medical and breastfeeding practitioners. The data presented here is intended to provide some
             information but cannot replace input from professionals.</p>''', unsafe_allow_html=True
             )

    config_options()
    init_messages()
    
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Accept user input
    if question := st.chat_input("Ask the question about drugs in breastmilk."):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(question)
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            question = question.replace("'", "")
    
            with st.spinner(f"{st.session_state.model_name} thinking..."):
                response, linked_url = answer_question(question)            
                urls = ""
                for url in linked_url:
                    urls += f"[{url}]({url}) "
                message_placeholder.markdown(response + "\n\n" + urls)

        st.session_state.messages.append({"role": "assistant", "content": response})

    # Add "Clear chat" button under the chat
    st.button( ":violet-background[Clear chat]", on_click=init_messages)

                
if __name__ == "__main__":
    main()


