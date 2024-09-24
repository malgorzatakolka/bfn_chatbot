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

    st.sidebar.button("Start Over", key="clear_conversation", on_click=init_messages)

def init_messages():

    # Initialize chat history
    if st.session_state.clear_conversation or "messages" not in st.session_state:
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
    for i in range(start_index, len(st.session_state.messages) -1):
        chat_history.append(st.session_state.messages[i])
    return chat_history
    
def summarize_question_with_history(chat_history, question):
# To get the right context, use the LLM to first summarize the previous conversation
# This will be used to get embeddings and find similar chunks in the docs for context

    prompt = f"""
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natual language. 
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
    
    summary = session.sql(cmd, params=[st.session_state.model_name, prompt])
    st.markdown(summary)

    if st.session_state.debug:
        st.sidebar.text("Summary to be used to find similar chunks in the docs:")
        st.sidebar.caption(summary)

    return summary.replace("'", "")

def create_prompt (myquestion):

    chat_history = get_chat_history()

    if chat_history != []: #There is chat_history, so not first question
        question_summary = summarize_question_with_history(chat_history, myquestion)
        prompt_context =  get_similar_chunks_search_service(question_summary)
    else:
        prompt_context = get_similar_chunks_search_service(myquestion) #First question when using history

  
    prompt = f"""
           You are an expert chat assistance that extracs information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags..
           When ansering the question contained between <question> and </question> tags
           be concise and do not hallucinate. 
           If you don´t have the information just say so.
           
           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your asnwer.

           Only anwer the question if you can extract it from the CONTEXT provideed.
           
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
    st.markdown('<h1 class="seledin-title">Breastfeeding Network Drug in Breastmilk Document Assistant</h1>', unsafe_allow_html=True)
    
    st.write('''<p style="color:purple;">The information provided is taken from various reference source. It is provided as a guideline.
             No responsibility can be taken by the author or BfN for the way in which the information is used. 
             Clinical decisions remain the responsibility of medical and breastfeeding practitioners. The data presented here is intended to provide some
             information but cannot replace input from professionals</p>''', unsafe_allow_html=True
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

    
            question = question.replace("'","")
    
            with st.spinner(f"{st.session_state.model_name} thinking..."):
                response, linked_url = answer_question(question)            
                urls = "Docs: "
                for url in linked_url:
                    urls += f"[{url}]({url}) "
                    message_placeholder.markdown(response + "\n\n" + urls)

        st.session_state.messages.append({"role": "assistant", "content": response})


                
if __name__ == "__main__":
    main()




# import streamlit as st # Import python packages
# from snowflake.snowpark.context import get_active_session

# from snowflake.cortex import Complete
# from snowflake.core import Root

# import pandas as pd
# import json

# pd.set_option("max_colwidth",None)

# ### Default Values
# NUM_CHUNKS = 3 # Num-chunks provided as context. Play with this to check how it affects your accuracy
# slide_window = 7 # how many last conversations to remember. This is the slide window.

# # service parameters
# CORTEX_SEARCH_DATABASE = "BFN_PROJECT"
# CORTEX_SEARCH_SCHEMA = "DATA"
# CORTEX_SEARCH_SERVICE = "CC_SEARCH_SERVICE_CS"
# ######
# ######

# # columns to query in the service
# COLUMNS = [
#     "chunk",
#     "relative_path",
#     "category"
# ]

# cnx = st.connection('snowflake')
# session = cnx.session()
# root = Root(session)                         
                    

# svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]
   
# ### Functions
     
# def config_options():

#     st.sidebar.selectbox('Select your model:',(
#                                     'mixtral-8x7b',
#                                     'snowflake-arctic',
#                                     'mistral-large',
#                                     'llama3-8b',
#                                     'llama3-70b',
#                                     'reka-flash',
#                                      'mistral-7b',
#                                      'llama2-70b-chat',
#                                      'gemma-7b'), key="model_name")

#     categories = session.table('docs_chunks_table').select('category').distinct().collect()

#     cat_list = ['ALL']
#     for cat in categories:
#         cat_list.append(cat.CATEGORY)
            
#     st.sidebar.selectbox('Select what products you are looking for', cat_list, key = "category_value")

#     st.sidebar.checkbox('Do you want that I remember the chat history?', key="use_chat_history", value = True)

#     st.sidebar.checkbox('Debug: Click to see summary generated of previous conversation', key="debug", value = True)
#     st.sidebar.button("Start Over", key="clear_conversation", on_click=init_messages)
#     st.sidebar.expander("Session State").write(st.session_state)

# def init_messages():

#     # Initialize chat history
#     if st.session_state.clear_conversation or "messages" not in st.session_state:
#         st.session_state.messages = []

# def get_similar_chunks_search_service(query):

#     if st.session_state.category_value == "ALL":
#         response = svc.search(query, COLUMNS, limit=NUM_CHUNKS)
#     else: 
#         filter_obj = {"@eq": {"category": st.session_state.category_value} }
#         response = svc.search(query, COLUMNS, filter=filter_obj, limit=NUM_CHUNKS)

#     st.sidebar.json(response.json())
    
#     return response.json()  

# def get_chat_history():
# #Get the history from the st.session_stage.messages according to the slide window parameter
    
#     chat_history = []
    
#     start_index = max(0, len(st.session_state.messages) - slide_window)
#     for i in range (start_index , len(st.session_state.messages) -1):
#          chat_history.append(st.session_state.messages[i])

#     return chat_history

# def summarize_question_with_history(chat_history, question):
# # To get the right context, use the LLM to first summarize the previous conversation
# # This will be used to get embeddings and find similar chunks in the docs for context

#     prompt = f"""
#         Based on the chat history below and the question, generate a query that extend the question
#         with the chat history provided. The query should be in natual language. 
#         Answer with only the query. Do not add any explanation.
        
#         <chat_history>
#         {chat_history}
#         </chat_history>
#         <question>
#         {question}
#         </question>
#         """
    
#     sumary = Complete(st.session_state.model_name, prompt)   

#     if st.session_state.debug:
#         st.sidebar.text("Summary to be used to find similar chunks in the docs:")
#         st.sidebar.caption(sumary)

#     sumary = sumary.replace("'", "")

#     return sumary

# def create_prompt (myquestion):

#     if st.session_state.use_chat_history:
#         chat_history = get_chat_history()

#         if chat_history != []: #There is chat_history, so not first question
#             question_summary = summarize_question_with_history(chat_history, myquestion)
#             prompt_context =  get_similar_chunks_search_service(question_summary)
#         else:
#             prompt_context = get_similar_chunks_search_service(myquestion) #First question when using history
#     else:
#         prompt_context = get_similar_chunks_search_service(myquestion)
#         chat_history = ""
  
#     prompt = f"""
#            You are an expert chat assistance that extracs information from the CONTEXT provided
#            between <context> and </context> tags.
#            You offer a chat experience considering the information included in the CHAT HISTORY
#            provided between <chat_history> and </chat_history> tags..
#            When ansering the question contained between <question> and </question> tags
#            be concise and do not hallucinate. 
#            If you don´t have the information just say so.
           
#            Do not mention the CONTEXT used in your answer.
#            Do not mention the CHAT HISTORY used in your asnwer.

#            Only anwer the question if you can extract it from the CONTEXT provideed.
           
#            <chat_history>
#            {chat_history}
#            </chat_history>
#            <context>          
#            {prompt_context}
#            </context>
#            <question>  
#            {myquestion}
#            </question>
#            Answer: 
#            """
    
#     json_data = json.loads(prompt_context)

#     relative_paths = set(item['relative_path'] for item in json_data['results'])

#     return prompt, relative_paths


# def answer_question(myquestion):

#     prompt, relative_paths =create_prompt (myquestion)

#     response = Complete(st.session_state.model_name, prompt)   

#     return response, relative_paths

# def main():
    
#     st.title(f":speech_balloon: Chat Document Assistant with Snowflake Cortex")
#     st.write("This is the list of documents you already have and that will be used to answer your questions:")
#     docs_available = session.sql("ls @docs").collect()
#     list_docs = []
#     for doc in docs_available:
#         list_docs.append(doc["name"])
#     st.dataframe(list_docs)

#     config_options()
#     init_messages()
     
#     # Display chat messages from history on app rerun
#     for message in st.session_state.messages:
#         with st.chat_message(message["role"]):
#             st.markdown(message["content"])
    
#     # Accept user input
#     if question := st.chat_input("What do you want to know about your products?"):
#         # Add user message to chat history
#         st.session_state.messages.append({"role": "user", "content": question})
#         # Display user message in chat message container
#         with st.chat_message("user"):
#             st.markdown(question)
#         # Display assistant response in chat message container
#         with st.chat_message("assistant"):
#             message_placeholder = st.empty()
    
#             question = question.replace("'","")
    
#             with st.spinner(f"{st.session_state.model_name} thinking..."):
#                 response, relative_paths = answer_question(question)            
#                 response = response.replace("'", "")
#                 message_placeholder.markdown(response)

#                 if relative_paths != "None":
#                     with st.sidebar.expander("Related Documents"):
#                         for path in relative_paths:
#                             cmd2 = f"select GET_PRESIGNED_URL(@docs, '{path}', 360) as URL_LINK from directory(@docs)"
#                             df_url_link = session.sql(cmd2).to_pandas()
#                             url_link = df_url_link._get_value(0,'URL_LINK')
                
#                             display_url = f"Doc: [{path}]({url_link})"
#                             st.sidebar.markdown(display_url)

        
#         st.session_state.messages.append({"role": "assistant", "content": response})


# if __name__ == "__main__":
#     main()
