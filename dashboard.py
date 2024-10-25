import streamlit as st
from pyzbar.pyzbar import decode
from PIL import Image
import re
import numpy as np
import requests
import json
import firebase_admin
from firebase_admin import credentials, db

# st.title("Welcome to your dashboard")
def email_to_username(email):
    return re.sub(r'@.*$', '', email)

def add_UPC(upc, uid, db):
    user_ref = db.reference(f"users/{uid}/upcs")
    current_data = user_ref.get()
    
    # If no data exists for the user, initialize the UPC list
    if current_data is None:
        user_ref.set([upc])  # Initialize with the first UPC
        return "No UPC list found. Created a new list with the first UPC."

    # If UPC list exists, append to it
    elif isinstance(current_data, list):
        if upc not in current_data:  # Avoid duplicate UPCs
            current_data.append(upc)
            user_ref.set(current_data)
            return "UPC added to the existing list."
        else:
            return "UPC already exists in the list."
    
    return "Error handling UPC."




if 'user_info' in st.session_state:
    st.title(f"Hello there {email_to_username(st.session_state['user_info']['email'])} 👋! Feel free to ask any medical questions you have.")
    cred = credentials.Certificate("congressional-app-challe-2a799-firebase-adminsdk-bytd1-8af7255913.json")
    firebase_admin.initialize_app(cred, {"databaseURL": "https://congressional-app-challe-2a799-default-rtdb.firebaseio.com/"})
    ref = db.reference("/")
    uid = st.session_state.user_info['localId']
    enable = st.checkbox("Enable camera")

    cam = st.camera_input("Scan barcode", enable=not enable)

    if cam is not None:
        img = Image.open(cam)
        
        decoded = decode(img)
        st.write(decoded)
        decoded[0]
