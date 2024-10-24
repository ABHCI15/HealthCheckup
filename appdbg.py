import streamlit as st
import pathlib
import textwrap
import firebase_authfunctions as auth_functions

st.set_page_config(layout="wide", page_title="HealthInsight", page_icon="🩺")

# Dynamic Background and Custom Styling
st.markdown(
    """
    <style>
    .st-emotion-cache-ch5dnh {
      visibility: hidden;
      display: none;
    }
    body {
        background: url('https://example.com/background-image.jpg');  /* Replace with actual image URL */
        background-size: cover;
        font-family: 'Arial', sans-serif;
    }
    .reportview-container {
        background-color: rgba(255, 255, 255, 0.8);
        padding: 2rem;
    }
    .stButton > button {
        background-color: #001f3f;
        color: white;
        border-radius: 8px;
        padding: 10px 20px;
    }
    .stButton > button:hover {
        background-color: #004080;
    }
    .stTextInput > div > input {
        border-radius: 6px;
        border: 1px solid #ccc;
        padding: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("RecallScan")
placeholder = st.empty()
placeholder.header("Login to access the app")

# Authentication form
if 'user_info' not in st.session_state:
    col1, col2, col3 = st.columns([1, 2, 1])

    # Authentication form layout
    do_you_have_an_account = col2.selectbox(label='Do you have an account?', options=('Yes', 'No', 'I forgot my password'))
    auth_form = col2.form(key='Authentication form', clear_on_submit=False)
    email = auth_form.text_input(label='Email', placeholder="Enter your email")
    password = auth_form.text_input(label='Password', type='password', placeholder="Enter your password") if do_you_have_an_account in {'Yes', 'No'} else auth_form.empty()
    auth_notification = col2.empty()

    # Sign In
    if do_you_have_an_account == 'Yes' and auth_form.form_submit_button(label='Sign In', use_container_width=True, type='primary'):
        with auth_notification, st.spinner('Signing in...'):
            auth_functions.sign_in(email, password)

    # Create Account
    elif do_you_have_an_account == 'No' and auth_form.form_submit_button(label='Create Account', use_container_width=True, type='primary'):
        with auth_notification, st.spinner('Creating account...'):
            auth_functions.create_account(email, password)

    # Password Reset
    elif do_you_have_an_account == 'I forgot my password' and auth_form.form_submit_button(label='Send Password Reset Email', use_container_width=True, type='primary'):
        with auth_notification, st.spinner('Sending password reset link...'):
            auth_functions.reset_password(email)

    # Authentication success and warning messages
    if 'auth_success' in st.session_state:
        auth_notification.success(st.session_state.auth_success)
        del st.session_state.auth_success
    elif 'auth_warning' in st.session_state:
        auth_notification.warning(st.session_state.auth_warning)
        del st.session_state.auth_warning

# User information and sign out if logged in
else:
    placeholder.header('User information:')
    uid = st.session_state.user_info['localId']

    # Sign out and delete account
    st.header('Account Actions:')
    if st.button('Sign Out', type='primary'):
        auth_functions.sign_out()
    if st.button('Delete Account', type='primary'):
        password = st.text_input('Confirm your password', type='password')
        auth_functions.delete_account(password)

    # Navigation buttons
    if st.button('Proceed to Dashboard'):
        st.switch_page("dashboard")
    if st.button('Chat'):
        st.switch_page("chat")
