import streamlit as st 
# from langchain_google_genai import GoogleGenerativeAI
# from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain.agents.agent_types import AgentType
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
# import pandas as pd
# import plotly.express as px
from langchain_core.tools import Tool
# from langchain_experimental.utilities import PythonREPL
from langchain_community.tools.pubmed.tool import PubmedQueryRun
from langchain_community.agent_toolkits.load_tools import load_tools
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.tools.wikidata.tool import WikidataAPIWrapper, WikidataQueryRun
import os 
from langchain.agents import create_tool_calling_agent
from langchain_community.callbacks.streamlit import (
    StreamlitCallbackHandler,
)
from langchain_community.chat_message_histories import (
    StreamlitChatMessageHistory,
)
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    HarmBlockThreshold,
    HarmCategory,
)
from langchain_community.utilities import ArxivAPIWrapper
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_community.tools import WikipediaQueryRun, ArxivQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
import re
import os 
import json
from langchain.pydantic_v1 import BaseModel, Field
from langchain.tools import BaseTool, StructuredTool, tool

@tool
def find_matching_recall(upc_code: str) -> list:
    """ Inputting a 12 digit upc code as a string will return a list of recalls that match the upc code, if the upc code is not present in the database, the list will be empty. """
    os.system("curl https://www.saferproducts.gov/RestWebServices/Recall?format=json > output.json")
    with open("output.json", 'r') as f:
        recalls = json.load(f)
    matches = []
    for recall in recalls:
        for product_upc in recall['ProductUPCs']:
            if product_upc['UPC'] == upc_code:
                matches.append(recall)
    return matches


tool_wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
tool_wikidata = WikidataQueryRun(api_wrapper=WikidataAPIWrapper())
os.environ["TAVILY_API_KEY"] = st.secrets["TAVILY_API_KEY"]
# TavilySearchAPIWrapper = TavilySearchAPIWrapper(tavily_api_key=st.secrets["TAVILY_API_KEY"])
tool_med = PubmedQueryRun()
tool_search = TavilySearchResults()
tool_arxiv = ArxivQueryRun(api_wrapper=ArxivAPIWrapper())
st.markdown(
    """
    <style>
.st-emotion-cache-ch5dnh {
  visibility: hidden;
  display: none;
}

</style>
    """,
    unsafe_allow_html=True
)
def email_to_username(email):
    return re.sub(r'@.*$', '', email)

if 'user_info' in st.session_state:
    st.title(f"Hello there {email_to_username(st.session_state['user_info']['email'])} 👋! I'm here to assist you with your products!")
    


    text = st.chat_input(placeholder="Type your message here...")


    prompt = prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful assistant, who will try your best to deliver accurate and helpful information to the user regarding recalled products. You have access to the following tools: Pubmed, Tavily Search, Wikipedia, Arxiv and Wikidata. Use tavily when prompted of current real world conditions (use sparingly as it costs money ), Pubmed for medical research, Wikipedia for general information, Arxiv for scientific papers, and Wikidata for general knowledge. You should always cross reference with Pubmed first, then use other tools if needed. Always use the tools (except sparingly use tavily) rather than answering on your own, for examplre use wikipedia to answer who sa person is (or arxiv if they are academic). Always answer in an organized manner using markdown if needed or even latex, answer in depth. Always be sure to use tools to answer questions.",
            ),
            ("placeholder", "{history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    tools = [tool_med, tool_search, tool_wikipedia, tool_wikidata, tool_arxiv, find_matching_recall]
    # prompt.format(tools=tools, tool_names=[tool.name for tool in tools])
    llm = ChatGoogleGenerativeAI(model="models/gemini-1.5-pro-exp-0827", temperature=0.5, google_api_key=st.secrets["api_key"], safety_settings={ HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE})
    # llm.bind_tools(tools)
    agent = create_tool_calling_agent(llm,tools=tools, prompt=prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)


    history = StreamlitChatMessageHistory(key=st.session_state.user_info['email']) # add user id as key
    if len(history.messages) == 0:
        history.add_ai_message("Hello 👋, Welcome to Recall Q&A, please note that this is not intended to provide medical advice and merely exists as a small research aid.")

    for msg in history.messages:
        st.chat_message(msg.type).write(msg.content)
        
    if prompt :=text:
        with st.chat_message("user"):
            st.write(prompt)
            history.add_user_message(prompt)
        with st.chat_message("assistant"):
            st_callback = StreamlitCallbackHandler(st.container())
            response = agent_executor.invoke({"input": prompt, "history": history.messages}, {"callbacks": [st_callback]})
            st.write(response["output"])
            history.add_ai_message(response["output"])

else:
    st.warning("Please login to access this page")
    login = st.button("Login")
    if login:
        st.switch_page("app.py")