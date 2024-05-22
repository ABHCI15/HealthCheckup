import streamlit as st 
from langchain_google_genai import GoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents.agent_types import AgentType
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
import pandas as pd
import plotly.express as px
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    HarmBlockThreshold,
    HarmCategory,
)



st.title('Congressional App Challennge 2024')

element = st.chat_input('Enter your message here')

llm = GoogleGenerativeAI()

with element:
    if element:
        message = HumanMessage(element)
        response = llm.get_response(message)
        st.chat_message(response.text)


