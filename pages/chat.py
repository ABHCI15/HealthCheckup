import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, db

cred = credentials.Certificate("../congressional-app-challe-2a799-firebase-adminsdk-bytd1-8af7255913.json")
firebase_admin.initialize_app(cred)

ref = db.reference("/")
uid = st.session_state.user_info['localId']

