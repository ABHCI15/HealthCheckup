import streamlit as st
from pyzbar.pyzbar import decode
from PIL import Image
import re
import json
import firebase_admin
from firebase_admin import credentials, db
import smtplib
import google.generativeai as genai
import os

def debugEmail():
    upc_debug =  708953651019
    os.system("curl https://www.saferproducts.gov/RestWebServices/Recall?format=json > output.json")
    with open("output.json", 'r') as f:
        recalls = json.load(f)
    recall_matches = find_matching_recall(recalls, upc_debug)
    for recall in recall_matches:
        send_notification("Email", st.session_state['user_info']['email'], recall2msg(recall))
    st.success("Email sent")

# Function to extract username from email
def email_to_username(email):
    return re.sub(r'@.*$', '', email)

def recall2msg(recall):
    genai.configure(api_key=st.secrets['api_key'])
    genai_model = genai.GenerativeModel(model_name='models/gemini-1.5-pro-latest')
    prompt = f"Product with UPC {recall['ProductUPCs'][0]['UPC']} has been recalled of the user guide them to properly deal with the recalled product in the form of a brief paragraph with the following information from the recall database: {recall}"
    response = genai_model.generate_content(prompt)
    return response.text

def add_UPC(upc, uid, db):
    user_ref = db.reference(f"users/{uid}/upcs")
    current_data = user_ref.get()
    
    if current_data is None:
        user_ref.set([upc])  
        return "UPC list initialized with the first entry."
    elif isinstance(current_data, list):
        if upc not in current_data:
            current_data.append(upc)
            user_ref.set(current_data)
            return "UPC added to the list."
        else:
            return "UPC already exists in the list."
    return "Error handling UPC."

# Function to send notifications (email/SMS) for recalls
def send_notification(notification_type, contact_info, message):
    if notification_type == "Email":
        recipient = contact_info
        auth = (st.secrets['EMAIL'], st.secrets['PASSWORD'])
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(auth[0], auth[1])
        server.sendmail(auth[0], recipient, message)

    st.success(f"Notification sent to {contact_info}")

# Function to find recall matches for the scanned UPC
def find_matching_recall(recalls, upc_code):
    matches = []
    for recall in recalls:
        for product_upc in recall['ProductUPCs']:
            if product_upc['UPC'] == upc_code:
                matches.append(recall)
    return matches

# Streamlit dashboard
if 'user_info' in st.session_state:
    # Greeting message with user's email
    st.title(f"Hello there {email_to_username(st.session_state['user_info']['email'])} 👋! Recall Scan is here to help!")
    
    # Initialize Firebase
    cred = credentials.Certificate("congressional-app-challe-2a799-firebase-adminsdk-bytd1-8af7255913.json")
    if not firebase_admin._apps:  # Avoid initializing multiple times
        firebase_admin.initialize_app(cred, {"databaseURL": "https://congressional-app-challe-2a799-default-rtdb.firebaseio.com/"})
    
    uid = st.session_state.user_info['localId']
    
    # Display the number of products the user is tracking
    user_ref = db.reference(f"users/{uid}/upcs")
    tracked_upcs = user_ref.get()
    product_count = len(tracked_upcs) if tracked_upcs else 0
    st.write(f"You are currently tracking {product_count} products.")

    # Camera input for barcode scanning
    st.header("Scan or enter a product barcode to check for recalls")
    upc_inp = st.text_input("Enter UPC code")
    submit_upc = st.button("Submit UPC")
    if submit_upc:
        upc_code = upc_inp
        st.write(f"UPC code entered: {upc_code}")
        
        # Add UPC to Firebase
        result = add_UPC(upc_code, uid, db)
        st.write(result)

        # Recall check
        os.system("curl https://www.saferproducts.gov/RestWebServices/Recall?format=json > output.json")
        with open("output.json", 'r') as f:
            recalls = json.load(f)
        recall_matches = find_matching_recall(recalls, upc_code)

        if recall_matches:
            st.error("Product has been recalled!")
            for recall in recall_matches:
                st.write(f"Description: {recall['Description']}")
                st.write(recall2msg(recall))
        else:
            st.success("Product is safe.")
            
    st.write("OR")
    enable = st.checkbox("Enable camera")
    cam = st.camera_input("Scan barcode", disabled=not enable)

    if cam is not None:
        img = Image.open(cam)
        decoded = decode(img)
        
        if decoded:
            upc_code = decoded[0].data.decode('utf-8')
            st.write(f"UPC code detected: {upc_code}")

            # Add UPC to Firebase
            result = add_UPC(upc_code, uid, db)
            st.write(result)

            # Recall check
            os.system("curl https://www.saferproducts.gov/RestWebServices/Recall?format=json > output.json")
            with open("output.json", 'r') as f:
                recalls = json.load(f)
            recall_matches = find_matching_recall(recalls, upc_code)

            if recall_matches:
                st.error("Product has been recalled!")
                for recall in recall_matches:
                    st.write(f"Description: {recall['Description']}")
            else:
                st.success("Product is safe.")
    
    # Section for users to provide contact information for notifications
    st.write("Enter your contact information to get notified if any of your products are recalled.")
    
    # notification_type = st.radio("Notification method", ["Email", "Phone"])
    

    if st.button("Submit Email"):
        # send_notification("Email", st.session_state['user_info']['email'], "You will be notified of any recalls.")
        debugEmail()


    # Button for signing out
    if st.button("Sign Out"):
        st.session_state.pop('user_info', None)
        st.experimental_rerun()
    

